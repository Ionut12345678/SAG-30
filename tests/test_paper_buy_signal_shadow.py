import json
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from radar.paper_buy_signal_shadow import audit

class TestPaperBuySignal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"radar.db"
        self.cx=sqlite3.connect(self.db)
        self.cx.execute("""CREATE TABLE early_paper_extra_observations(
            run_id INTEGER,session TEXT,symbol TEXT,discovery_ts TEXT,discovery_pct REAL,
            quote_retrieved_ts TEXT,trade_ts TEXT,quote_ts TEXT,bid REAL,ask REAL,
            trade_price REAL,spread_pct REAL,screen_stage TEXT,blockers_json TEXT,feed TEXT)""")
        self.now=datetime(2026,10,12,13,31,tzinfo=timezone.utc)
    def tearDown(self):
        self.cx.close()
        self.tmp.cleanup()
    def insert(self,symbol="ABC",stage="EARLY_PAPER_ENTRY_REVIEW",ts="2026-10-12T13:30:00Z",ask=1.03,blockers="[]"):
        self.cx.execute("INSERT INTO early_paper_extra_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1,"2026-10-12",symbol,"2026-10-12T13:25:00Z",2.0,ts,
             "2026-10-12T13:29:59Z","2026-10-12T13:29:59Z",
             1.01,ask,1.02,1.96,stage,blockers,"iex"))
        self.cx.commit()
    def test_prospective_first_signal_immutable_and_no_order(self):
        self.insert()
        r=audit(self.db,self.tmp.name,self.now)
        self.assertEqual(r["new_signals"],1)
        e=r["new_events"][0]
        self.assertEqual(e["signal_at"]["bucharest"],"2026-10-12T16:30:00+03:00")
        self.assertFalse(e["order_allowed"])
        self.assertFalse(e["fill_confirmed"])
        self.assertEqual(e["indicative_ask"],1.03)
        ledger=Path(self.tmp.name)/"shadow_first_paper_buy_signal.jsonl"
        first=ledger.read_text()
        self.assertEqual(audit(self.db,self.tmp.name,self.now)["new_signals"],0)
        self.assertEqual(ledger.read_text(),first)
    def test_blocked_is_not_buy(self):
        self.insert(stage="RECHECK_FAST")
        r=audit(self.db,self.tmp.name,self.now)
        self.assertEqual(r["new_signals"],0)
        self.assertEqual(r["funnel_counts"]["blocked_NOT_PAPER_ENTRY_REVIEW"],1)
    def test_stale_and_missing_quote_are_not_buy(self):
        self.insert(symbol="OLD",ts="2026-10-12T12:00:00Z")
        self.insert(symbol="BAD",ask=None)
        r=audit(self.db,self.tmp.name,self.now)
        self.assertEqual(r["new_signals"],0)
        self.assertEqual(r["funnel_counts"]["blocked_INVALID_ASK"],1)
        self.assertEqual(r["funnel_counts"]["blocked_STALE_OR_FUTURE_CAPTURE"],1)
if __name__=="__main__":unittest.main()
