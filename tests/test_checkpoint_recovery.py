import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from radar.checkpoint import prepare, file_sha
from radar.recovery import recover

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.db'
        with sqlite3.connect(self.source) as db:
            db.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY, first_seen TEXT)')
            db.execute("INSERT INTO audit VALUES(1,'2026-10-09T13:00:00Z')")
        self.destination=self.root/'active.db';shutil.copy(self.source,self.destination)
        with sqlite3.connect(self.source) as db:
            db.execute("INSERT INTO audit VALUES(2,'2026-10-12T13:00:00Z')")
        self.parts=self.root/'parts'
        self.manifest=prepare(self.source,self.parts,base_commit='a'*40,run_id='123',part_bytes=1024)
        # Model the original v1 artifact (before journal inventories existed).
        self.manifest.pop('journals',None)
        (self.parts/'checkpoint.json').write_text(json.dumps(self.manifest))
        (self.parts/'shadow_first_watch.jsonl').write_text('{"first_seen":"immutable"}\n')
        self.archive=self.root/'archive.zip'
        self.zip_parts()
        self.artifact={'id':1,'expired':False,'created_at':'2026-10-12T13:10:00Z','workflow_run':{'id':123}}
        self.workflow={'path':'.github/workflows/radar.yml','head_branch':'main'}
        self.forensic=[]
    def tearDown(self):self.temp.cleanup()
    def zip_parts(self):
        with zipfile.ZipFile(self.archive,'w') as zipped:
            for path in self.parts.iterdir():zipped.write(path,path.name)
    def api(self,path):
        if 'name=sag30-checkpoint-forensic' in path:return {'artifacts':self.forensic}
        if 'name=sag30-checkpoint-recovery' in path:return {'artifacts':[self.artifact]}
        return self.workflow
    def download(self,cmd,stdout,check):
        stdout.write(self.archive.read_bytes())
    def recover(self):
        with patch('radar.recovery.gh_json',side_effect=self.api),patch('radar.recovery.subprocess.run',side_effect=self.download):
            return recover('owner/repo','a'*40,self.destination,self.root/'status.json',self.root/'journals','2026-10-12T13:00:00+00:00')
    def test_end_to_end_failed_publication_requires_artifact_and_verified_restore(self):
        # Model a completed prospective scan with a failed/cancelled push.
        # No following scan is admitted until the exact prepared checkpoint
        # has been independently restored and the published audit preserved.
        from datetime import datetime, timezone
        from radar.restart import (
            admission, verify_required_recovery, RESTORE, RECOVERY, SCAN, PREPARE, PERSIST,
        )
        now = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
        health = {
            'generated_ts': '2026-10-12T13:00:00+00:00',
            'checkpoint': {'workflow_run_id': '122'},
            'latest_run': {'started': '2026-10-12T13:00:00+00:00'},
            'observations': {'ok': 1, 'valid_source_latest_ts': '2026-10-12T13:00:00+00:00'},
        }
        previous = {
            'id': 123, 'status': 'completed',
            'steps': {
                RESTORE: {'conclusion': 'success'},
                RECOVERY: {'conclusion': 'success'},
                SCAN: {'conclusion': 'success', 'started_at': '2026-10-12T13:05:00+00:00'},
                PREPARE: {'conclusion': 'success'},
                PERSIST: {'conclusion': 'failure'},
            },
        }
        # Missing artifact (historical cancellation) is not recoverable by fiat.
        blocked = admission(now, health, [previous], current_id=124)
        self.assertEqual(blocked['reason'], 'UNPUBLISHED_CYCLE_WITHOUT_RECOVERY')
        self.assertFalse(blocked['allowed'])
        previous['recovery_artifact_available'] = True
        gated = admission(now, health, [previous], current_id=124)
        self.assertTrue(gated['allowed'])
        self.assertEqual(gated['reason'], 'RECOVERY_REQUIRED')
        self.assertEqual(gated['required_recovery_run_id'], '123')
        with self.assertRaises(ValueError):
            verify_required_recovery({'status': 'NO_COMPATIBLE_RECOVERY_ARTIFACT'}, '123')
        before = file_sha(self.destination)
        result = self.recover()  # checksum, parent, journal, audit extension
        self.assertEqual(result['status'], 'RESTORED_RECOVERY_ARTIFACT')
        verify_required_recovery(result, gated['required_recovery_run_id'])
        self.assertNotEqual(file_sha(self.destination), before)
        with sqlite3.connect(self.destination) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0], 2)
        # A forged success for the wrong run must never authorize collection.
        with self.assertRaises(ValueError):
            verify_required_recovery(result, '567')

    def test_failed_push_snapshot_recovers_before_next_scan(self):
        result=self.recover()
        self.assertEqual(result['status'],'RESTORED_RECOVERY_ARTIFACT')
        with sqlite3.connect(self.destination) as db:
            self.assertEqual(db.execute('SELECT * FROM audit ORDER BY id').fetchall(),[(1,'2026-10-09T13:00:00Z'),(2,'2026-10-12T13:00:00Z')])
        self.assertEqual((self.root/'journals/shadow_first_watch.jsonl').read_text(),'{"first_seen":"immutable"}\n')
    def test_parent_mismatch_cannot_overwrite_newer_state(self):
        original=file_sha(self.destination)
        self.manifest['base_commit']='b'*40
        (self.parts/'checkpoint.json').write_text(json.dumps(self.manifest));self.zip_parts()
        self.assertEqual(self.recover()['status'],'NO_COMPATIBLE_RECOVERY_ARTIFACT')
        self.assertEqual(file_sha(self.destination),original)
    def test_unmerged_branch_artifact_not_used(self):
        self.workflow['head_branch']='fix/other'
        self.assertEqual(self.recover()['status'],'NO_COMPATIBLE_RECOVERY_ARTIFACT')
    def test_corrupt_artifact_cannot_replace_existing_audit(self):
        original=file_sha(self.destination)
        (self.parts/self.manifest['parts'][0]['name']).write_bytes(b'corruption');self.zip_parts()
        with self.assertRaises(ValueError):self.recover()
        self.assertEqual(file_sha(self.destination),original)
    def test_run_identity_mismatch_is_blocked(self):
        self.manifest['workflow_run_id']='999'
        (self.parts/'checkpoint.json').write_text(json.dumps(self.manifest));self.zip_parts()
        with self.assertRaises(ValueError):self.recover()
    def test_api_outage_is_not_treated_as_absence(self):
        with patch('radar.recovery.gh_json',side_effect=subprocess.CalledProcessError(1,'gh')):
            with self.assertRaises(subprocess.CalledProcessError):recover('owner/repo','a'*40,self.destination,self.root/'status.json')
    def test_recent_expired_and_forensic_evidence_blocks_scan(self):
        self.artifact['expired']=True
        with self.assertRaises(ValueError):self.recover()
        self.artifact['expired']=False
        self.forensic=[self.artifact]
        with self.assertRaises(ValueError):self.recover()
    def test_artifact_older_than_published_checkpoint_is_skipped(self):
        self.artifact['created_at']='2026-10-09T13:00:00Z'
        self.assertEqual(self.recover()['status'],'NO_COMPATIBLE_RECOVERY_ARTIFACT')

    def test_journal_rewrite_cannot_change_first_watch(self):
        journals=self.root/'journals';journals.mkdir()
        (journals/'shadow_first_watch.jsonl').write_text('{"first_seen":"published"}\n')
        before=file_sha(self.destination)
        with self.assertRaises(ValueError):self.recover()
        self.assertEqual(file_sha(self.destination),before)
        self.assertEqual((journals/'shadow_first_watch.jsonl').read_text(),'{"first_seen":"published"}\n')

    def test_declared_missing_or_corrupt_journal_is_rejected(self):
        import hashlib
        name='shadow_first_watch.jsonl'
        payload=(self.parts/name).read_bytes()
        self.manifest['journals']=[{'name':name,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]
        (self.parts/'checkpoint.json').write_text(json.dumps(self.manifest))
        (self.parts/name).write_text('valid ZIP but altered journal')
        self.zip_parts();before=file_sha(self.destination)
        with self.assertRaises(ValueError):self.recover()
        self.assertEqual(file_sha(self.destination),before)

    def test_published_audit_rows_cannot_be_removed_from_valid_artifact(self):
        # A checksum-consistent snapshot can still regress the published parent.
        for path in (self.source,self.destination):
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY, retrieval_ts TEXT)')
                db.execute("INSERT INTO observations VALUES(1,'published')")
        with sqlite3.connect(self.source) as db:
            db.execute('DELETE FROM observations')
        shutil.rmtree(self.parts)
        self.manifest=prepare(self.source,self.parts,base_commit='a'*40,run_id='123')
        self.zip_parts();before=file_sha(self.destination)
        with self.assertRaisesRegex(ValueError,'published audit'):self.recover()
        self.assertEqual(file_sha(self.destination),before)

    def test_published_first_seen_cannot_be_rewritten(self):
        for path in (self.source,self.destination):
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE model_state(symbol TEXT PRIMARY KEY, first_seen TEXT, first_radar_seen TEXT)')
                db.execute("INSERT INTO model_state VALUES('TEST','published','first radar')")
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE model_state SET first_seen='backdated'")
        shutil.rmtree(self.parts)
        self.manifest=prepare(self.source,self.parts,base_commit='a'*40,run_id='123')
        self.zip_parts();before=file_sha(self.destination)
        with self.assertRaisesRegex(ValueError,'first_seen'):self.recover()
        self.assertEqual(file_sha(self.destination),before)

    def test_new_audit_rows_and_first_radar_initialization_are_allowed(self):
        for path in (self.source,self.destination):
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY, retrieval_ts TEXT)')
                db.execute("INSERT INTO observations VALUES(1,'published')")
                db.execute('CREATE TABLE model_state(symbol TEXT PRIMARY KEY, first_seen TEXT, first_radar_seen TEXT)')
                db.execute("INSERT INTO model_state VALUES('TEST','published',NULL)")
        with sqlite3.connect(self.source) as db:
            db.execute("INSERT INTO observations VALUES(2,'new retrieval')")
            db.execute("UPDATE model_state SET first_radar_seen='new retrieval'")
        shutil.rmtree(self.parts)
        self.manifest=prepare(self.source,self.parts,base_commit='a'*40,run_id='123')
        self.zip_parts()
        self.assertEqual(self.recover()['status'],'RESTORED_RECOVERY_ARTIFACT')

    def test_staging_io_failure_leaves_original_database_intact(self):
        original=file_sha(self.destination)
        entries={path.name for path in self.root.iterdir()}
        copy=shutil.copyfileobj
        def fail_sibling_copy(src,dst,*args,**kwargs):
            if hasattr(dst,'name') and Path(str(dst.name)).parent==self.root:
                raise OSError('synthetic disk full')
            return copy(src,dst,*args,**kwargs)
        with patch('radar.recovery.shutil.copyfileobj',side_effect=fail_sibling_copy):
            with self.assertRaises(OSError):self.recover()
        self.assertEqual(file_sha(self.destination),original)
        self.assertEqual({path.name for path in self.root.iterdir()},entries)

    def test_new_manifest_cannot_smuggle_unhashed_journal(self):
        self.manifest['journals']=[]
        (self.parts/'checkpoint.json').write_text(json.dumps(self.manifest));self.zip_parts()
        original=file_sha(self.destination)
        with self.assertRaisesRegex(ValueError,'not declared'):self.recover()
        self.assertEqual(file_sha(self.destination),original)

    def test_newest_failed_snapshot_wins_even_when_its_id_is_lower(self):
        old_archive=self.archive.read_bytes()
        with sqlite3.connect(self.source) as db:
            db.execute("INSERT INTO audit VALUES(3,'newest prospective observation')")
        shutil.rmtree(self.parts)
        self.manifest=prepare(self.source,self.parts,base_commit='a'*40,run_id='124')
        self.zip_parts();new_archive=self.archive.read_bytes()
        older={'id':900,'expired':False,'created_at':'2026-10-12T13:10:00Z','workflow_run':{'id':123}}
        newer={'id':100,'expired':False,'created_at':'2026-10-12T13:20:00Z','workflow_run':{'id':124}}
        def api(path):
            if 'name=sag30-checkpoint-forensic' in path:return {'artifacts':[]}
            if 'name=sag30-checkpoint-recovery' in path:return {'artifacts':[older,newer]}
            return self.workflow
        def download(cmd,stdout,check):
            stdout.write(new_archive if '/100/zip' in cmd[-1] else old_archive)
        with patch('radar.recovery.gh_json',side_effect=api),patch('radar.recovery.subprocess.run',side_effect=download):
            result=recover('owner/repo','a'*40,self.destination,self.root/'status.json',base_published_ts='2026-10-12T13:00:00+00:00')
        self.assertEqual(result['artifact_id'],100)
        with sqlite3.connect(self.destination) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],3)

    def test_equal_creation_times_are_not_guessed_from_ids(self):
        def api(path):
            if 'name=sag30-checkpoint-forensic' in path:return {'artifacts':[]}
            if 'name=sag30-checkpoint-recovery' in path:
                return {'artifacts':[self.artifact,dict(self.artifact,id=2)]}
            return self.workflow
        with patch('radar.recovery.gh_json',side_effect=api):
            with self.assertRaisesRegex(ValueError,'Ambiguous'):
                recover('owner/repo','a'*40,self.destination,self.root/'status.json')
