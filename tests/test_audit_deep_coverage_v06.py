import sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_deep_coverage_v06 import audit
class TestCoverage(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"a.sqlite"
  c=sqlite3.connect(self.path)
  c.executescript("""CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,run_id INTEGER,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER,selected INTEGER);
 CREATE TABLE observations(run_id INTEGER,symbol TEXT,retrieval_ts TEXT,quality TEXT);""")
  t="2026-10-09T13:00:00+00:00"
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09","AAA",t,1,5,3,2,1))
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09","BBB",t,1,5,4,3,0))
  c.execute("INSERT INTO observations VALUES (?,?,?,?)",(1,"AAA","2026-10-09T13:00:05+00:00","OK"))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_selected_vs_unselected(self):
  r=audit(self.path);self.assertEqual(r["counts"]["discovery"],2)
  self.assertEqual(r["counts"]["SELECTED_SAME_RUN_DEEP"],1)
  self.assertEqual(r["counts"]["unselected_no_deep_within_15m"],1)
if __name__=="__main__":unittest.main()
