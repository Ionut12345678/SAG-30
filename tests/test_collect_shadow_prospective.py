"""Regression tests for append-only prospective SHADOW collector."""
import sqlite3,tempfile,unittest
from pathlib import Path
from radar.collect_shadow_prospective import collect

class TestProspectiveCollector(unittest.TestCase):
 def test_append_only_idempotent_and_first_snapshot(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Path(tmp)/"radar.sqlite3";ledger=Path(tmp)/"ledger.jsonl"
   conn=sqlite3.connect(db)
   conn.execute("""CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,
    run_id INTEGER,change_pct REAL,selected INTEGER,rank_change INTEGER,rank_turnover INTEGER)""")
   conn.executemany("INSERT INTO scout_history VALUES(?,?,?,?,?,?,?,?)",[
    ("2026-10-08","OLD","2026-10-08T10:00:00+00:00",1,2,1,1,1),
    ("2026-10-09","ABC","2026-10-09T10:00:00+00:00",2,4,0,95,35),
    ("2026-10-09","ABC","2026-10-09T11:00:00+00:00",3,8,1,1,1),
    ("2026-10-09","XYZ","2026-10-09T10:00:00+00:00",2,12,0,1,1)])
   conn.commit();conn.close()
   a=collect(db,ledger);b=collect(db,ledger)
   self.assertEqual(a["new_records"],1)
   self.assertEqual(b["new_records"],0)
   import json
   row=json.loads(ledger.read_text().strip())
   self.assertEqual(row["symbol"],"ABC")
   self.assertEqual(row["run_id"],2)
   self.assertTrue(row["priority"])
   self.assertFalse(row["baseline"])
if __name__=="__main__":unittest.main()
