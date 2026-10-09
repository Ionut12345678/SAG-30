import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from radar.audit_leadtime_prospective import audit


class LeadtimeAuditTest(unittest.TestCase):
    def test_future_cohort_and_subsecond_guard(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "data.sqlite3"
            ledger = Path(root) / "ledger.jsonl"
            c = sqlite3.connect(db)
            c.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL)")
            c.executemany("INSERT INTO scout_history VALUES(?,?,?,?)", [
                ("2026-10-12", "WIN", "2026-10-12T14:00:00Z", 2),
                ("2026-10-12", "WIN", "2026-10-12T14:15:00Z", 5),
                ("2026-10-12", "WIN", "2026-10-12T14:20:00Z", 32),
                ("2026-10-12", "WIN", "2026-10-12T14:30:00Z", 51),
                ("2026-10-12", "SAME", "2026-10-12T14:00:00Z", 5),
                ("2026-10-12", "SAME", "2026-10-12T14:00:00.067Z", 70),
                ("2026-10-13", "NEXT", "2026-10-13T14:00:00Z", 1)])
            c.commit()
            c.close()
            ledger.write_text("\n".join(json.dumps({
                "session": "2026-10-12", "symbol": s,
                "first_eligible_ts": "2026-10-12T14:00:00Z",
                "first_change_pct": p}) for s, p in [("WIN", 2), ("SAME", 5)]))
            r = audit(db, ledger)
            cases = {row["symbol"]: row for row in r["cases"]}
            self.assertEqual(cases["WIN"]["onset_status"], "EARLY_10M")
            self.assertEqual(cases["WIN"]["lead_minutes"], 15)
            self.assertTrue(cases["WIN"]["observed_50_after_scout"])
            self.assertFalse(cases["SAME"]["observed_30_after_scout"])
            self.assertEqual(r["cohort"]["observed_later_50"], 1)

    def test_backdating_rejected(self):
        with self.assertRaises(ValueError):
            audit("unused", "unused", start_session="2026-10-09")
