import sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_routing_swap_v08 import audit
class TestRoutingSwap(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"t.db"
  c=sqlite3.connect(self.path)
  c.execute("CREATE TABLE scout_history(session TEXT,run_id INTEGER,symbol TEXT,retrieval_ts TEXT,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER,selected INTEGER)")
  for s,pct,rank,selected in [("EARLY",5,1,0),("OTHER",12,80,1)]:
   c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",1,s,"2026-10-09T13:00:00Z",pct,rank,rank,selected))
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",2,"EARLY","2026-10-09T13:10:00Z",35,1,1,1))
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",2,"OTHER","2026-10-09T13:10:00Z",15,70,70,1))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_gain_and_loss(self):
  x=audit(self.path)["variants"]["5"]
  self.assertEqual(x["added"],1);self.assertEqual(x["displaced"],1)
  self.assertEqual(x["added_later30"],1);self.assertEqual(x["displaced_later30"],0)
  self.assertEqual(x["net_later30"],1)
 def test_baseline_zero_swaps(self):
  x=audit(self.path)["variants"]["0"]
  self.assertEqual(x["added"],0);self.assertEqual(x["displaced"],0)
if __name__=="__main__":unittest.main()
