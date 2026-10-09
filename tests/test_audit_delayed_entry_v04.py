import json,sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_delayed_entry_v04 import audit
T0="2026-10-09T13:00:00+00:00"
T1="2026-10-09T13:01:00+00:00"
T2="2026-10-09T13:04:00+00:00"
Q={"latestTrade":{"p":10,"t":T1},"latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":T1}}
class TestDelayedEntry(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/"a.sqlite"
  c=sqlite3.connect(self.db)
  c.executescript("""CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,run_id INTEGER,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER);
 CREATE TABLE observations(symbol TEXT,retrieval_ts TEXT,quality TEXT,payload TEXT,price REAL,change_pct REAL);""")
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?)",("2026-10-09","AAA",T0,1,5,10,5))
  c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",("AAA",T1,"OK",json.dumps(Q),10,5))
  c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",("AAA",T2,"OK","{}",11,15))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_delayed_quote_paper(self):
  r=audit(self.db)
  self.assertEqual(r["counts"]["paper_review"],1)
  self.assertEqual(r["counts"]["outcome_observed"],1)
  self.assertEqual(r["examples"][0]["delay_seconds"],60)
 def test_first_quote_stale_not_skip_to_future_good(self):
  c=sqlite3.connect(self.db)
  c.execute("UPDATE observations SET payload='{}' WHERE retrieval_ts=?",(T1,))
  c.commit();c.close()
  r=audit(self.db)
  self.assertNotIn("paper_review",r["counts"])
  self.assertEqual(r["counts"]["quote_screen_blocked"],1)
if __name__=="__main__":unittest.main()
