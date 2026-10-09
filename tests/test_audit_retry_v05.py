import json,sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_retry_v05 import audit
T0="2026-10-09T13:00:00+00:00"
T1="2026-10-09T13:00:10+00:00"
T2="2026-10-09T13:01:15+00:00"
T3="2026-10-09T13:02:00+00:00"
def quote(ts):
 return json.dumps({"latestTrade":{"p":10,"t":ts},
  "latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":ts}})
class TestRetryV05(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"test.sqlite"
  c=sqlite3.connect(self.path)
  c.executescript("""CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,run_id INTEGER,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER);
 CREATE TABLE observations(symbol TEXT,retrieval_ts TEXT,quality TEXT,payload TEXT,price REAL,change_pct REAL);""")
  c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?)",("2026-10-09","AAA",T0,1,5,10,3))
  c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",("AAA",T1,"OK","{}",10,5))
  c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",("AAA",T2,"OK",quote(T2),10,5))
  c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",("AAA",T3,"OK","{}",11,15))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_retry_after_due_not_backdated(self):
  r=audit(self.path)
  self.assertEqual(r["counts"]["retry_rescued"],1)
  self.assertEqual(r["paper_cases"][0]["paper_entry_ts"],T2)
  self.assertEqual(r["paper_cases"][0]["retry_offset_seconds"],60)
  self.assertEqual(r["paper_cases"][0]["outcome"]["max_future_observed_price"],11)
 def test_no_future_quote_as_initial(self):
  c=sqlite3.connect(self.path)
  c.execute("DELETE FROM observations WHERE retrieval_ts=?",(T1,))
  c.commit();c.close()
  r=audit(self.path)
  self.assertEqual(r["counts"]["first_quote_pass"],1)
  self.assertEqual(r["paper_cases"][0]["paper_entry_ts"],T2)
 def test_expired_quote_never_selected(self):
  c=sqlite3.connect(self.path)
  c.execute("UPDATE observations SET retrieval_ts=? WHERE retrieval_ts=?",
            ("2026-10-09T13:20:00+00:00",T2))
  c.commit();c.close()
  r=audit(self.path)
  self.assertNotIn("paper_ready",r["counts"])
if __name__=="__main__":unittest.main()
