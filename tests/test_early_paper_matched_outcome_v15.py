import sqlite3,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from radar.early_paper_matched_outcome_v15 import build
class MatchedOutcomes(unittest.TestCase):
 def test_future_only_and_missing_not_loss(self):
  with TemporaryDirectory() as d:
   path=str(Path(d)/"a.db");db=sqlite3.connect(path)
   db.execute("CREATE TABLE early_paper_extra_observations(run_id INTEGER,session TEXT,symbol TEXT,discovery_pct REAL,ask REAL,trade_price REAL,screen_stage TEXT)")
   db.execute("CREATE TABLE scout_history(run_id INTEGER,session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,acceleration_pp_per_min REAL,fresh_turnover_impulse_per_min REAL)")
   db.execute("INSERT INTO early_paper_extra_observations VALUES(3,'2026-10-09','AAA',2,10,10,'EARLY_PAPER_ENTRY_REVIEW')")
   for run in (1,2,3,4,5):
    ts=f'2026-10-09T14:{run*5:02d}:00+00:00'
    for symbol,pct in [('AAA',2 if run<=3 else (40 if run==4 else 3)),('BBB',2.1)]:
     db.execute("INSERT INTO scout_history VALUES(?,'2026-10-09',?,?,?,1,1)",(run,symbol,ts,pct))
   db.commit();db.close()
   x=build(path);w=x["windows"]["60m"]
   self.assertEqual(w["paper"]["observed_hit30"],1)
   self.assertEqual(w["controls"]["observed_hit30"],0)
   self.assertEqual(w["paired_with_both_observed"],1)
 def test_no_future_samples_is_censored(self):
  with TemporaryDirectory() as d:
   path=str(Path(d)/"a.db");db=sqlite3.connect(path)
   db.execute("CREATE TABLE early_paper_extra_observations(run_id INTEGER,session TEXT,symbol TEXT,discovery_pct REAL,ask REAL,trade_price REAL,screen_stage TEXT)")
   db.execute("CREATE TABLE scout_history(run_id INTEGER,session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,acceleration_pp_per_min REAL,fresh_turnover_impulse_per_min REAL)")
   db.execute("INSERT INTO early_paper_extra_observations VALUES(1,'2026-10-09','AAA',2,10,10,'EARLY_PAPER_ENTRY_REVIEW')")
   db.execute("INSERT INTO scout_history VALUES(1,'2026-10-09','AAA','2026-10-09T14:05:00+00:00',2,1,1)")
   db.commit();db.close()
   x=build(path)["windows"]["60m"]["paper"]
   self.assertEqual(x["with_future_samples"],0)
   self.assertEqual(x["observed_hit30"],0)
if __name__=="__main__":unittest.main()
