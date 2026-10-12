import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from radar.checkpoint import MIB, BLOB_LIMIT, file_sha, prepare, restore_directory, restore_git, size_status

class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'audit.sqlite3'
        db = sqlite3.connect(self.db_path)
        db.executescript('CREATE TABLE audit(id INTEGER PRIMARY KEY, source_ts TEXT, retrieval_ts TEXT, payload BLOB); CREATE TABLE first_seen(symbol TEXT PRIMARY KEY, first_seen_ts TEXT NOT NULL);')
        db.execute('INSERT INTO audit VALUES(?,?,?,?)',(1,'2026-10-12T13:30:00Z','2026-10-12T13:31:00Z',os.urandom(20000)))
        db.execute("INSERT INTO first_seen VALUES('TEST','2026-10-09T14:00:00Z')")
        db.commit()
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_size_boundaries_80_90(self):
        for size,expected in [(80*MIB-1,'OK'),(80*MIB,'WARNING_80_MIB'),(90*MIB-1,'WARNING_80_MIB'),(90*MIB,'CRITICAL_90_MIB'),(100*MIB,'CRITICAL_90_MIB')]:
            self.assertEqual(size_status(size),expected)

    def test_round_trip_split_keeps_every_row_and_first_seen(self):
        original = file_sha(self.db_path)
        out = self.root / 'checkpoint'
        manifest = prepare(self.db_path,out,base_commit='a'*40,run_id='100',part_bytes=4096)
        self.assertGreater(len(manifest['parts']),1)
        self.assertTrue(all(p['bytes']<=4096 for p in manifest['parts']))
        restored = self.root / 'restored.db'
        counts = restore_directory(out,restored)
        self.assertEqual(counts,{'audit':1,'first_seen':1})
        with sqlite3.connect(self.db_path) as old,sqlite3.connect(restored) as new:
            self.assertEqual(list(old.iterdump()),list(new.iterdump()))
        self.assertEqual(file_sha(self.db_path),original)
        self.assertEqual(file_sha(restored),manifest['database_sha256'])

    def test_checkpoint_above_old_95_mib_limit_is_lossless(self):
        # Incompressible fixture exercises the real old limit, not a mocked size.
        with sqlite3.connect(self.db_path) as db:
            db.execute('INSERT INTO audit VALUES(?,?,?,?)',(2,'source','retrieval',os.urandom(96*MIB)))
        out=self.root/'over-limit'
        manifest=prepare(self.db_path,out)
        self.assertGreater(manifest['compressed_bytes'],95*MIB)
        self.assertTrue(all(part['bytes'] < 95*MIB for part in manifest['parts']))
        restored=self.root/'over-limit.db'
        self.assertEqual(restore_directory(out,restored)['audit'],2)
        with sqlite3.connect(self.db_path) as src,sqlite3.connect(restored) as dst:
            import hashlib
            self.assertEqual(hashlib.sha256(src.execute('SELECT payload FROM audit WHERE id=2').fetchone()[0]).hexdigest(),hashlib.sha256(dst.execute('SELECT payload FROM audit WHERE id=2').fetchone()[0]).hexdigest())

    def test_wal_committed_transaction_is_included(self):
        writer=sqlite3.connect(self.db_path)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("INSERT INTO first_seen VALUES('WAL','2026-10-12T13:00:00Z')")
        writer.commit()
        self.assertTrue(Path(str(self.db_path)+'-wal').exists())
        out=self.root/'wal'
        prepare(self.db_path,out)
        restored=self.root/'wal-restored.db'
        restore_directory(out,restored)
        with sqlite3.connect(restored) as db:
            self.assertEqual(db.execute("SELECT first_seen_ts FROM first_seen WHERE symbol='WAL'").fetchone()[0],'2026-10-12T13:00:00Z')
        writer.close()

    def test_legacy_gzip_and_raw_restoration(self):
        for compressed in (True,False):
            root=self.root/str(compressed)
            root.mkdir()
            if compressed:
                (root/'radar.sqlite3.gz').write_bytes(gzip.compress(self.db_path.read_bytes()))
            else:
                shutil.copy(self.db_path,root/'radar.sqlite3')
            restore_directory(root,self.root/f'legacy-{compressed}.db')

    def test_corrupt_part_cannot_replace_existing_database(self):
        out=self.root/'parts'
        manifest=prepare(self.db_path,out,part_bytes=4096)
        destination=self.root/'existing.db'
        shutil.copy(self.db_path,destination)
        original=file_sha(destination)
        part=out/manifest['parts'][0]['name']
        part.write_bytes(b'broken')
        with self.assertRaises(ValueError):restore_directory(out,destination)
        self.assertEqual(file_sha(destination),original)

    def test_missing_part_and_invalid_manifest_fail_closed(self):
        out=self.root/'parts'
        manifest=prepare(self.db_path,out)
        part=out/manifest['parts'][0]['name']
        part.unlink()
        with self.assertRaises(FileNotFoundError):restore_directory(out,self.root/'missing.db')
        manifest['parts'][0]['name']='../escape'
        (out/'checkpoint.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):restore_directory(out,self.root/'missing.db')
        self.assertFalse((self.root/'missing.db').exists())

    def test_manifest_db_hash_and_counts_verified(self):
        for field,value in [('database_sha256','0'*64),('table_counts',{'audit':0})]:
            out=self.root/field
            manifest=prepare(self.db_path,out)
            manifest[field]=value
            (out/'checkpoint.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):restore_directory(out,self.root/(field+'.db'))

    def test_invalid_sqlite_and_oversized_part_rejected(self):
        path=self.root/'bad.db';path.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):prepare(path,self.root/'bad')
        with self.assertRaises(ValueError):prepare(self.db_path,self.root/'big',part_bytes=BLOB_LIMIT)

    def test_restore_cannot_overwrite_live_wal(self):
        out=self.root/'parts';prepare(self.db_path,out)
        Path(str(self.db_path)+'-wal').touch()
        with self.assertRaises(ValueError):restore_directory(out,self.db_path)

    def test_git_manifest_and_legacy_transport(self):
        for split in (True,False):
            repo=self.root/str(split);repo.mkdir()
            if split:prepare(self.db_path,repo,part_bytes=4096)
            else:(repo/'radar.sqlite3.gz').write_bytes(gzip.compress(self.db_path.read_bytes()))
            for cmd in [['git','init','-q'],['git','add','.'],['git','-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','snapshot']]:
                subprocess.run(cmd,cwd=repo,check=True,capture_output=True)
            counts=restore_git(repo,'HEAD',self.root/f'git-{split}.db')
            self.assertEqual(counts['first_seen'],1)

    def test_health_size_alert_does_not_claim_publication(self):
        health=self.root/'health.json';health.write_text('{"health":"PASS","fast_scout":{"status":"DATA_GAP"}}')
        with patch('radar.checkpoint.size_status',return_value='CRITICAL_90_MIB'):
            prepare(self.db_path,self.root/'parts',health_path=health)
        result=json.loads(health.read_text())
        self.assertEqual(result['checkpoint']['publication'],'PREPARED_NOT_CONFIRMED')
        self.assertEqual(result['health'],'DEGRADED')
        self.assertEqual(result['fast_scout']['status'],'DATA_GAP')

    def test_journals_are_hashed_before_manifest_completion(self):
        journals=self.root/'journals';journals.mkdir()
        path=journals/'shadow_first_watch.jsonl';path.write_text('{"first_seen":"immutable"}\n')
        out=self.root/'journal-checkpoint'
        manifest=prepare(self.db_path,out,journal_dir=journals)
        self.assertEqual(manifest['journals'],[{'name':path.name,'bytes':path.stat().st_size,'sha256':file_sha(path)}])
        self.assertEqual((out/path.name).read_bytes(),path.read_bytes())
