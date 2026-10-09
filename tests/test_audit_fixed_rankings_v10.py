import sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_fixed_rankings_v10 import audit
class TestFixedRankings(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"t.db"
  c=sqlite3.connect(self.path)
  c.execute("CREATE TABLE scout_history(session TEXT,run_id INTEGER,symbol TEXT,retrieval_ts TEXT,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER,selected INTEGER)")
  for s,rank,turn in [("A",1,10),("B",10,1)]:
   c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",1,s,"2026-10-09T13:00:00Z",5,rank,turn,0))
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",2,"A","2026-10-09T13:10:00Z",35,1,1,1))
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",2,"B","2026-10-09T13:10:00Z",6,2,2,1))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_rank_methods_distinct(self):
  r=audit(self.path,budget=1)["total"]
  self.assertEqual(r["change"]["later30"],1)
  self.assertEqual(r["turnover"].get("later30",0),0)
if __name__=="__main__":unittest.main()
