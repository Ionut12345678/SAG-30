"""Regression checks for exact PAPER review timestamps; never BUY."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from radar.shadow_entry_timeline import capture

class TestPaperTimeline(unittest.TestCase):
    def test_first_review_is_immutable_and_not_a_buy(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"state.db"
            cx=sqlite3.connect(db)
            cx.execute("""CREATE TABLE early_paper_extra_observations(
              run_id INTEGER,session TEXT,symbol TEXT,discovery_ts TEXT,discovery_pct REAL,
              quote_retrieved_ts TEXT,trade_ts TEXT,quote_ts TEXT,bid REAL,ask REAL,
              trade_price REAL,spread_pct REAL,screen_stage TEXT,blockers_json TEXT,feed TEXT)""")
            cx.execute("INSERT INTO early_paper_extra_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (1,"2026-10-12","TEST","2026-10-12T13:25:00Z",2.0,
               "2026-10-12T13:30:00Z","2026-10-12T13:29:59Z","2026-10-12T13:29:59Z",
               1.0,1.02,1.01,1.98,"EARLY_PAPER_ENTRY_REVIEW","[]","iex"))
            cx.commit()
            now=datetime(2026,10,12,13,31,tzinfo=timezone.utc)
            result=capture(db,d,now)
            self.assertEqual(result["new_reviews"],1)
            e=result["new_events"][0]
            self.assertEqual(e["retrieved_at"]["et"],"2026-10-12T09:30:00-04:00")
            self.assertEqual(e["retrieved_at"]["bucharest"],"2026-10-12T16:30:00+03:00")
            self.assertEqual(e["trading_action"],"NONE")
            ledger=Path(d)/"shadow_first_paper_review.jsonl"
            first=ledger.read_text()
            self.assertEqual(capture(db,d,now)["new_reviews"],0)
            self.assertEqual(ledger.read_text(),first)
            cx.close()

    def test_stale_friday_not_backfilled_monday(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"state.db"
            cx=sqlite3.connect(db)
            cx.execute("""CREATE TABLE early_paper_extra_observations(
              run_id INTEGER,session TEXT,symbol TEXT,discovery_ts TEXT,discovery_pct REAL,
              quote_retrieved_ts TEXT,trade_ts TEXT,quote_ts TEXT,bid REAL,ask REAL,
              trade_price REAL,spread_pct REAL,screen_stage TEXT,blockers_json TEXT,feed TEXT)""")
            cx.execute("INSERT INTO early_paper_extra_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (1,"2026-10-09","OLD",None,1.0,"2026-10-09T19:30:00Z",None,None,
               None,None,None,None,"EARLY_PAPER_ENTRY_REVIEW","[]","iex"))
            cx.commit()
            result=capture(db,d,datetime(2026,10,12,13,30,tzinfo=timezone.utc))
            self.assertEqual(result["new_reviews"],0)
            self.assertEqual(result["skipped"]["wrong_session"],1)
            cx.close()

if __name__=="__main__":unittest.main()
