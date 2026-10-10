"""Prospective-only WATCH journal regression tests."""
import json
import sqlite3
import tempfile
from datetime import datetime,timezone
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
            first=capture(db,d,as_of=datetime(2026,10,9,13,6,tzinfo=timezone.utc))
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
    def test_friday_not_replayed_monday_and_timezone_offsets(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"scout.sqlite3"
            cx=sqlite3.connect(db)
            cx.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,run_id INTEGER)")
            cx.execute("INSERT INTO scout_history VALUES (?,?,?,?,?)",("2026-10-09","FRIDAY","2026-10-09T19:30:00Z",4.0,1))
            cx.commit()
            result=capture(db,d,as_of=datetime(2026,10,12,13,30,tzinfo=timezone.utc))
            self.assertEqual(result["new_watches"],0)
            self.assertEqual(result["session_skipped"],1)
            cx.execute("INSERT INTO scout_history VALUES (?,?,?,?,?)",("2026-10-12","MONDAY","2026-10-12T13:30:00Z",4.0,2))
            cx.commit()
            result=capture(db,d,as_of=datetime(2026,10,12,13,31,tzinfo=timezone.utc))
            self.assertEqual(result["new_watches"],1)
            watch=json.loads((Path(d)/"shadow_first_watch.jsonl").read_text())
            self.assertEqual(watch["retrieval_ts_et"],"2026-10-12T09:30:00-04:00")
            self.assertEqual(watch["retrieval_ts_bucharest"],"2026-10-12T16:30:00+03:00")
            cx.close()

    def test_stale_and_future_observations_are_not_watch(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"scout.sqlite3"
            cx=sqlite3.connect(db)
            cx.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,run_id INTEGER)")
            for sym,ts in [("STALE","2026-10-12T13:00:00Z"),("FUTURE","2026-10-12T13:40:00Z")]:
                cx.execute("INSERT INTO scout_history VALUES (?,?,?,?,?)",("2026-10-12",sym,ts,4.0,1))
            cx.commit()
            result=capture(db,d,as_of=datetime(2026,10,12,13,30,tzinfo=timezone.utc))
            self.assertEqual(result["new_watches"],0)
            self.assertEqual(result["stale_skipped"],1)
            self.assertEqual(result["future_skipped"],1)
            cx.close()

if __name__=="__main__":unittest.main()
