import sqlite3,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from radar.early_paper_momentum_shadow_v14 import build
class MomentumShadowTest(unittest.TestCase):
 def test_no_lookahead_and_matched_controls(self):
  with TemporaryDirectory() as d:
   path=str(Path(d)/"audit.sqlite")
   db=sqlite3.connect(path)
   db.execute("CREATE TABLE early_paper_extra_observations(run_id INTEGER,session TEXT,symbol TEXT,discovery_pct REAL,ask REAL,trade_price REAL,screen_stage TEXT)")
   db.execute("CREATE TABLE scout_history(run_id INTEGER,session TEXT,symbol TEXT,change_pct REAL,acceleration_pp_per_min REAL,fresh_turnover_impulse_per_min REAL)")
   db.execute("INSERT INTO early_paper_extra_observations VALUES(3,'2026-10-09','AAA',2,10,9.9,'EARLY_PAPER_ENTRY_REVIEW')")
   for run in (1,2,3,4):
    db.execute("INSERT INTO scout_history VALUES(?,'2026-10-09','AAA',2,?,?)",(run,1 if run!=4 else -5,1 if run!=4 else -5))
    db.execute("INSERT INTO scout_history VALUES(?,'2026-10-09','BBB',2.1,-1,-1)",(run,))
   db.commit();db.close()
   report=build(path)
   self.assertEqual(report["paper"]["both_positive_3"],1)
   self.assertEqual(report["matched_controls"]["both_positive_3"],0)
   self.assertEqual(report["paper_cases"][0]["entry_run_id"],3)
if __name__=="__main__":unittest.main()
