import sqlite3,unittest
from datetime import datetime,timezone
from radar.early_paper_follow_v12 import init,pending,observe
class TestFollow(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(":memory:")
  self.db.execute("""CREATE TABLE early_paper_extra_observations(
  run_id INTEGER,session TEXT,symbol TEXT,discovery_ts TEXT,discovery_pct REAL,
  quote_retrieved_ts TEXT,trade_ts TEXT,quote_ts TEXT,bid REAL,ask REAL,
  trade_price REAL,spread_pct REAL,screen_stage TEXT,blockers_json TEXT,feed TEXT)""")
  self.entry="2026-10-09T13:00:00+00:00"
  self.db.execute("INSERT INTO early_paper_extra_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
   (1,"2026-10-09","AURA",self.entry,2,self.entry,self.entry,self.entry,9.9,10,9.95,1,"EARLY_PAPER_ENTRY_REVIEW","[]","iex"))
 def test_follow_observed_30_from_ask(self):
  now=datetime.fromisoformat("2026-10-09T13:10:00+00:00")
  later="2026-10-09T13:09:00+00:00"
  r=observe(self.db,2,now,{},"iex",lambda url,h:({"AURA":{"latestTrade":{"p":13.1,"t":later}}},now.isoformat()))
  self.assertEqual(r["fresh"],1)
  self.assertGreater(self.db.execute("SELECT indicative_return_pct FROM early_paper_follow_v12").fetchone()[0],30)
 def test_old_trade_not_counted(self):
  now=datetime.fromisoformat("2026-10-09T13:10:00+00:00")
  r=observe(self.db,2,now,{},"iex",lambda url,h:({"AURA":{"latestTrade":{"p":20,"t":self.entry}}},now.isoformat()))
  self.assertEqual(r["fresh"],0)
  self.assertIsNone(self.db.execute("SELECT indicative_return_pct FROM early_paper_follow_v12").fetchone()[0])
 def test_expired_entry_excluded(self):
  init(self.db)
  self.assertEqual(pending(self.db,datetime.fromisoformat("2026-10-20T13:00:00+00:00")),[])
if __name__=="__main__":unittest.main()
