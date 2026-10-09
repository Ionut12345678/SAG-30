import sqlite3,tempfile,unittest
from pathlib import Path
from radar.audit_reserved_early_slots_v07 import audit
class TestSlots(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"t.sqlite"
  c=sqlite3.connect(self.path)
  c.execute("CREATE TABLE scout_history(session TEXT,run_id INTEGER,symbol TEXT,retrieval_ts TEXT,change_pct REAL,rank_change INTEGER,rank_turnover INTEGER,selected INTEGER)")
  for s,rank,sel in [("AAA",1,0),("BBB",2,0),("CCC",3,1),("DDD",4,1)]:
   c.execute("INSERT INTO scout_history VALUES (?,?,?,?,?,?,?,?)",("2026-10-09",1,s,"2026-10-09T13:00:00Z",12 if sel else 5,rank,rank,sel))
  c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def test_slots_replace_not_inflate(self):
  r=audit(self.path,slots=(1,2))
  self.assertEqual(r["by_reserved_slots"]["1"]["hypothetical_extra_early_coverage"],1)
  self.assertEqual(r["by_reserved_slots"]["2"]["hypothetical_displaced_existing_selections"],2)
if __name__=="__main__":unittest.main()
