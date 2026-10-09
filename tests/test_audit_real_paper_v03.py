import json,sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_real_paper_v03 import audit

T="2026-10-09T13:00:00+00:00"
Q={"latestTrade":{"p":10,"t":T},"latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":T}}
class TestRealPaperAudit(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.db=Path(self.tmp.name)/"x.sqlite"
  c=sqlite3.connect(self.db)
  c.executescript("""CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,run_id INTEGER,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER);
  CREATE TABLE observations(run_id INTEGER,symbol TEXT,retrieval_ts TEXT,quality TEXT,payload TEXT,price REAL);""")
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?)",("2026-10-09","AAA",T,1,5,5,3))
  c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",(1,"AAA",T,"OK",json.dumps(Q),10))
  c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",(2,"AAA","2026-10-09T13:05:00+00:00","OK","{}",11))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_real_match_and_forward(self):
  r=audit(self.db);self.assertEqual(r["counts"]["paper_review"],1)
  self.assertEqual(r["counts"]["paper_with_later_observation"],1)
 def test_no_lookahead_on_later_deep_quote(self):
  c=sqlite3.connect(self.db)
  c.execute("UPDATE observations SET retrieval_ts=? WHERE run_id=1",("2026-10-09T13:01:00+00:00",))
  c.commit();c.close()
  r=audit(self.db)
  self.assertEqual(r["counts"]["no_contemporaneous_deep_snapshot"],1)
  self.assertNotIn("paper_review",r["counts"])
if __name__=="__main__":unittest.main()
