import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from radar.checkpoint import prepare
from radar.remote_restore_drill import verify


class RestoreDrillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.db = self.root / "db.sqlite3"
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE audit(id INTEGER PRIMARY KEY, first_seen TEXT NOT NULL)")
            db.execute("INSERT INTO audit VALUES(1,'immutable')")
        self.journals = self.root / "journals"
        self.journals.mkdir()
        (self.journals / "shadow_first_watch.jsonl").write_text('{"first":"immutable"}\n')
        prepare(self.db, self.repo, journal_dir=self.journals, part_bytes=4096)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.email=ci@example.invalid", "-c", "user.name=CI", "commit", "-qm", "valid")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def test_valid_published_snapshot(self):
        report = verify(self.repo, "HEAD", self.root / "result.json")
        self.assertEqual(report["status"], "RESTORE_VERIFIED")
        self.assertEqual(report["row_count"], 1)
        self.assertEqual(report["journal_verification"]["shadow_first_watch.jsonl"], "SHA256_OK")

    def test_tampered_published_journal_fails(self):
        (self.repo / "shadow_first_watch.jsonl").write_text('{"first":"rewritten"}\n')
        self.git("add", ".")
        self.git("-c", "user.email=ci@example.invalid", "-c", "user.name=CI", "commit", "-qm", "tamper")
        with self.assertRaisesRegex(ValueError, "journal checksum"):
            verify(self.repo, "HEAD", self.root / "invalid.json")

    def test_missing_checkpoint_segment_fails(self):
        (self.repo / "radar.sqlite3.gz.part-00000").unlink()
        self.git("add", "-A")
        self.git("-c", "user.email=ci@example.invalid", "-c", "user.name=CI", "commit", "-qm", "missing")
        with self.assertRaises(subprocess.CalledProcessError):
            verify(self.repo, "HEAD", self.root / "missing.json")


if __name__ == "__main__":
    unittest.main()
