import sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_additive_shadow_v09 import audit
class TestAdditive(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"a.db"
  c=sqlite3.connect(self.path)
  c.execute("CREATE TABLE scout_history(session TEXT,run_id INTEGER,symbol TEXT,retrieval_ts TEXT,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER,selected INTEGER)")
  for s,rank,turn,sel in [("A",2,2,0),("B",3,3,0),("C",4,4,1)]:
   c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",1,s,"2026-10-09T13:00:00Z",5,rank,turn,sel))
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",2,"A","2026-10-09T13:10:00Z",40,1,1,1))
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",2,"B","2026-10-09T13:10:00Z",6,2,2,1))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_no_displacement_and_budget(self):
  r=audit(self.path)["variants"]
  self.assertEqual(r["1"]["extra_requests_upper_bound"],1)
  self.assertEqual(r["1"]["later30"],1)
  self.assertEqual(r["3"]["extra_requests_upper_bound"],2)
  self.assertEqual(r["3"]["nonwinner30"],1)
 def test_zero_budget(self):
  self.assertEqual(audit(self.path)["variants"]["0"]["extra_requests_upper_bound"],0)
if __name__=="__main__":unittest.main()
