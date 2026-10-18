import tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from radar import connect,ingest,report,scan
class RadarTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.conn=connect(str(Path(self.temp.name)/"test.sqlite"))
 def tearDown(self):
  self.conn.close();self.temp.cleanup()
 def tick(self,minute,price,source_minute=None,reference=10):
  m=minute if source_minute is None else source_minute
  return {"symbol":"ABC","session":"2026-10-19","observed_at":f"2026-10-19T14:{minute:02d}:40Z",
  "source_ts":f"2026-10-19T14:{m:02d}:30Z","price":price,"previous_close":reference}
 def test_detect_early(self):
  self.assertEqual(ingest(self.conn,self.tick(0,10.6)),"FIRST_WATCH")
 def test_reject_late_first(self):
  self.assertEqual(ingest(self.conn,self.tick(0,12.0)),"OBSERVED_NO_SIGNAL")
  self.assertEqual(report(self.conn)["first_watches"],0)
 def test_follow_up_levels(self):
  ingest(self.conn,self.tick(0,10.6));ingest(self.conn,self.tick(5,12.3))
  self.assertEqual(report(self.conn)["signals"][0]["milestones_vs_previous_close"],[15,20])
 def test_gain_from_entry(self):
  ingest(self.conn,self.tick(0,10.6));ingest(self.conn,self.tick(5,12.3))
  self.assertAlmostEqual(report(self.conn)["signals"][0]["max_gain_from_entry_pct"],16.0377,places=3)
 def test_duplicate(self):
  ingest(self.conn,self.tick(0,10.6))
  self.assertEqual(ingest(self.conn,self.tick(0,10.6)),"DUPLICATE_OR_OUT_OF_ORDER")
 def test_reject_stale(self):
  self.assertEqual(ingest(self.conn,self.tick(5,10.6,0)),"REJECTED")
 def test_future(self):
  t=self.tick(0,10.6);t["source_ts"]="2026-10-19T14:00:41Z"
  self.assertEqual(ingest(self.conn,t),"REJECTED")
 def test_reference_change(self):
  ingest(self.conn,self.tick(0,10.6))
  self.assertEqual(ingest(self.conn,self.tick(5,12.3,reference=9)),"REJECTED")
 def test_missing_is_unknown(self):
  ingest(self.conn,self.tick(0,10.6))
  self.assertEqual(report(self.conn)["signals"][0]["result"],"UNKNOWN_NO_FOLLOW_UP")
 def test_empty_scan_data_gap(self):
  p={"provider":"fixture","session":"2026-10-19","quotes":[]}
  result=scan(self.conn,p,datetime(2026,10,19,14,0,tzinfo=timezone.utc))
  self.assertEqual(result["status"],"DATA_GAP")
 def test_no_buy(self):
  self.assertFalse(report(self.conn)["buy"])
  self.assertFalse(report(self.conn)["orders_enabled"])
if __name__=="__main__":unittest.main()
