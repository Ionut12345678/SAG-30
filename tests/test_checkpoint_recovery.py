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
