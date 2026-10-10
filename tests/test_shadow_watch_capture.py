"""Prospective-only WATCH journal regression tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from radar.shadow_watch_capture import capture

class TestProspectiveWatchCapture(unittest.TestCase):
    def test_first_watch_immutable_no_backfill_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"scout.sqlite3"
            cx=sqlite3.connect(db)
            cx.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,run_id INTEGER)")
            cx.execute("INSERT INTO scout_history VALUES (?,?,?,?,?)",("2026-10-09","TEST","2026-10-09T13:00:00Z",1.0,1))
            cx.execute("INSERT INTO scout_history VALUES (?,?,?,?,?)",("2026-10-09","TEST","2026-10-09T13:05:00Z",4.0,2))
            cx.commit()
            first=capture(db,d)
            self.assertEqual(first["new_watches"],1)
            journal=Path(d)/"shadow_first_watch.jsonl"
            before=journal.read_text()
            self.assertEqual(json.loads(before)["ts"],"2026-10-09T13:05:00Z")
            second=capture(db,d)
            self.assertEqual(second["new_watches"],0)
            self.assertEqual(second["new_observations"],0)
            self.assertEqual(before,journal.read_text())
            cx.close()

    def test_no_watch_on_non_trigger(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"scout.sqlite3"
            cx=sqlite3.connect(db)
            cx.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,run_id INTEGER)")
            cx.execute("INSERT INTO scout_history VALUES (?,?,?,?,?)",("2026-10-09","TEST","2026-10-09T13:05:00Z",1.0,1))
            cx.commit()
            self.assertEqual(capture(db,d)["new_watches"],0)
            self.assertFalse((Path(d)/"shadow_first_watch.jsonl").exists())
            cx.close()
if __name__=="__main__":unittest.main()
