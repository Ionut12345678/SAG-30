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
            self.assertEqual(x["top_observed_entry_relative"][0]["max_entry_relative_sampled_return_pct"],38.88889)
            self.assertEqual(r["horizons"]["240m"]["overall"]["sampled_entry_relative50"],1)
            self.assertEqual(x["lanes"]["priority"]["candidates"],0)

    def test_subsecond_same_cycle_peak_not_credited_as_future_gain(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, ledger = Path(tmp)/"data.db", Path(tmp)/"ledger.jsonl"
            db = sqlite3.connect(db_path)
            db.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL)")
            db.executemany("INSERT INTO scout_history VALUES(?,?,?,?)", [
                ("2026-10-09", "VIVK", "2026-10-09T13:32:32.476425+00:00", 82.61851),
                ("2026-10-09", "VIVK", "2026-10-09T13:32:33.000000+00:00", 82.61851),
                ("2026-10-09", "WFF", "2026-10-09T14:41:02.383261+00:00", 9.47867),
                ("2026-10-09", "WFF", "2026-10-09T15:54:57.715387+00:00", 73.45972)])
            db.commit()
            db.close()
            ledger.write_text("\\n".join(json.dumps(row) for row in [
                {"session":"2026-10-09","symbol":"VIVK",
                 "first_eligible_ts":"2026-10-09T13:32:32.409279+00:00",
                 "first_change_pct":7.81893},
                {"session":"2026-10-09","symbol":"WFF",
                 "first_eligible_ts":"2026-10-09T14:41:02.383261+00:00",
                 "first_change_pct":9.47867}])+"\\n")
            report = audit(db_path, ledger)
            v = next(x for x in report["horizons"]["60m"]["top_observed_entry_relative"]
                     if x["symbol"] == "VIVK") if any(
                         x["symbol"] == "VIVK" for x in report["horizons"]["60m"]["top_observed_entry_relative"]) else None
            self.assertIsNone(v)
            self.assertEqual(report["horizons"]["60m"]["overall"]["unverified_same_cycle_only"], 1)
            w = next(x for x in report["horizons"]["240m"]["top_observed_entry_relative"]
                     if x["symbol"] == "WFF")
            self.assertGreater(w["max_entry_relative_sampled_return_pct"], 50)

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
            ledger.write_text(json.dumps(row)+"\n"+json.dumps(row)+"\n")
            with self.assertRaises(ValueError):
                audit(db_path, ledger)

if __name__ == "__main__":
    unittest.main()
