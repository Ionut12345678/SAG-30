import unittest
from datetime import datetime,timezone,timedelta
from radar_cross_source import inspect_chart,run
N=datetime(2026,10,19,15,0,tzinfo=timezone.utc)
def chart(ts):
 return {"chart":{"result":[{"meta":{"regularMarketPrice":10.6,"chartPreviousClose":10.0,"regularMarketTime":int(ts.timestamp())}}]}}
class CrossSourceTests(unittest.TestCase):
 def test_recent_is_not_validated(self):
  r=inspect_chart("ABC",chart(N-timedelta(seconds=30)),N)
  self.assertEqual(r["status"],"RECENT_VENDOR_TIMESTAMP_UNVERIFIED")
  self.assertFalse(r["eligible_for_first_watch"])
  self.assertFalse(r["source_timestamp_verified_by_exchange"])
 def test_stale_source(self):
  r=inspect_chart("ABC",chart(N-timedelta(minutes=15)),N)
  self.assertEqual(r["status"],"STALE_TIMESTAMP")
 def test_bad_schema(self):
  r=inspect_chart("ABC",{},N)
  self.assertEqual(r["status"],"BAD_SCHEMA")
 def test_bounded_sample(self):
  d={"candidates":[{"symbol":"A"+str(i)} for i in range(12)]}
  r=run(d,N,fetch=lambda s:chart(N))
  self.assertEqual(r["requested"],12)
  self.assertEqual(r["verified_live_signals"],0)
 def test_feed_failure_no_buy(self):
  def error(s):raise TimeoutError()
  r=run({"candidates":[{"symbol":"ABC"}]},N,fetch=error)
  self.assertEqual(r["results"][0]["status"],"SOURCE_UNAVAILABLE")
  self.assertFalse(r["results"][0]["eligible_for_first_watch"])
if __name__=="__main__":unittest.main()
