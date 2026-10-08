"""Regression tests for rank ledger export; synthetic SQLite, no BUY."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from radar.export_rank_ledger import export

class ExportRankLedgerTests(unittest.TestCase):
    def test_rank_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.sqlite3"
            db=sqlite3.connect(path)
            db.execute("CREATE TABLE multi_engine_scores(run_id INTEGER,session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,score_rank INTEGER,base_selected INTEGER,dual_selected INTEGER)")
            db.executemany("INSERT INTO multi_engine_scores VALUES(?,?,?,?,?,?,?,?)",[
                (1,"2026-10-08","AAA","2026-10-08T15:00:00+00:00",4.5,7,0,1),
                (1,"2026-10-08","BBB","2026-10-08T15:00:00+00:00",2.0,25,0,0)])
            db.commit()
            db.close()
            rows=export(path)
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]["rank"],7)
            self.assertTrue(rows[0]["selected"])
            self.assertFalse(rows[1]["selected"])

    def test_missing_table_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.sqlite3"
            sqlite3.connect(path).close()
            with self.assertRaises(sqlite3.OperationalError):
                export(path)

if __name__=="__main__":
    unittest.main()
