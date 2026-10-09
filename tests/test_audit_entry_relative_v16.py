"""Deterministic guardrails for the read-only entry-relative sampled audit."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from radar.audit_entry_relative_v16 import audit

class EntryRelativeV16(unittest.TestCase):
    def test_entry_relative_not_absolute_and_no_lookahead(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, ledger = Path(tmp)/"data.db", Path(tmp)/"ledger.jsonl"
            db = sqlite3.connect(db_path)
            db.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL)")
            db.executemany("INSERT INTO scout_history VALUES(?,?,?,?)", [
                ("2026-10-09", "AAA", "2026-10-09T14:00:00+00:00", 8),
                ("2026-10-09", "AAA", "2026-10-09T14:10:00+00:00", 50),
                ("2026-10-09", "AAA", "2026-10-09T15:05:00+00:00", 150),
                ("2026-10-09", "BBB", "2026-10-09T14:10:00+00:00", 1),
                ("2026-10-09", "BBB", "2026-10-09T15:10:00+00:00", 1),
                ("2026-10-10", "AAA", "2026-10-10T14:00:00+00:00", 1000)])
            db.commit()
            db.close()
            ledger.write_text(json.dumps({"session":"2026-10-09","symbol":"AAA",
                "first_eligible_ts":"2026-10-09T14:00:00+00:00",
                "first_change_pct":8,"baseline":True,"discovery":True,"priority":False})+"\n")
            r = audit(db_path, ledger)
            x = r["horizons"]["60m"]
            self.assertEqual(x["overall"]["sampled_absolute50"], 1)
            self.assertEqual(x["overall"]["sampled_entry_relative50"], 0)
            self.assertEqual(x["overall"]["sampled_entry_relative30"], 1)
            self.assertEqual(x["overall"]["sampled_entry_relative10"], 1)
            self.assertEqual(x["overall"]["sampled_entry_relative15"], 1)
            self.assertEqual(x["overall"]["sampled_entry_relative20"], 1)
            self.assertEqual(x["overall"]["sampled_absolute10"], 1)
            self.assertEqual(x["overall"]["sampled_absolute15"], 1)
            self.assertEqual(x["overall"]["sampled_absolute20"], 1)
            self.assertEqual(x["top_observed_entry_relative"][0]["first_sampled_hit15_ts"],
                             "2026-10-09T14:10:00+00:00")
            self.assertIsNone(x["top_observed_entry_relative"][0]["first_sampled_hit50_ts"])
            self.assertEqual(x["top_observed_entry_relative"][0]["max_entry_relative_sampled_return_pct"],38.88889)
            self.assertEqual(r["horizons"]["240m"]["overall"]["sampled_entry_relative50"],1)
            self.assertEqual(r["horizons"]["240m"]["top_observed_entry_relative"][0]["first_sampled_hit50_ts"],
                             "2026-10-09T15:05:00+00:00")
            self.assertEqual(x["lanes"]["priority"]["candidates"],0)

    def test_censoring_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, ledger = Path(tmp)/"data.db", Path(tmp)/"ledger.jsonl"
            db = sqlite3.connect(db_path)
            db.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL)")
            db.execute("INSERT INTO scout_history VALUES('2026-10-09','AAA','2026-10-09T14:00:00+00:00',2)")
            db.commit()
            db.close()
            row = {"session":"2026-10-09","symbol":"AAA",
                   "first_eligible_ts":"2026-10-09T14:00:00+00:00","first_change_pct":2}
            ledger.write_text(json.dumps(row)+"\n")
            x = audit(db_path, ledger)["horizons"]["60m"]["overall"]
            self.assertEqual(x["pending_window"],1)
            self.assertEqual(x["sampled_entry_relative30"],0)
            self.assertEqual(x["sampled_entry_relative15"],0)
            ledger.write_text(json.dumps(row)+"\n"+json.dumps(row)+"\n")
            with self.assertRaises(ValueError):
                audit(db_path, ledger)

if __name__ == "__main__":
    unittest.main()
