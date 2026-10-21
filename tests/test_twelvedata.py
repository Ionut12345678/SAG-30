import unittest
from datetime import datetime,timezone,timedelta
from radar_twelvedata import parse,run
from radar_vendor_quotes import reconcile
NOW=datetime(2026,10,21,15,30,tzinfo=timezone.utc)
def data(minutes=3,price="12.5"):
 return {"status":"ok","meta":{"symbol":"AAA","interval":"1min"},"values":[{"datetime":(NOW-timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S"),"close":price}]}
class TwelveTests(unittest.TestCase):
 def test_without_key_does_not_request_market_data(self):
  r=run({"candidates":[{"symbol":"AAA"}]},now=NOW,key="",request=lambda s,k: self.fail("No API call permitted"))
  self.assertEqual(r["status"],"MISSING_API_KEY")
  self.assertEqual(r["requested"],0)
 def test_timestamp_from_completed_bar_not_now(self):
  r=parse("AAA",data(),NOW)
  self.assertEqual(r["status"],"RECENT_VENDOR_TIMESTAMP_UNVERIFIED")
  self.assertEqual(r["observed_price"],12.5)
  self.assertEqual(r["source_ts_utc"],(NOW-timedelta(minutes=3)).isoformat())
  self.assertFalse(r["source_timestamp_verified_by_exchange"])
 def test_fresh_bar_then_followup(self):
  a=parse("AAA",data(3,"10"),NOW)
  b=parse("AAA",data(2,"12.5"),NOW)
  s,_=reconcile({},{"provider":"Twelve Data","results":[a]})
  s,r=reconcile(s,{"provider":"Twelve Data","results":[b]})
  self.assertEqual(r["new_comparisons"],1)
  self.assertEqual(r["outcomes"][0]["return_pct"],25.0)
  self.assertEqual(r["source"],"Twelve Data")
 def test_reject_incomplete_and_old_bar(self):
  self.assertEqual(parse("AAA",data(0),NOW)["status"],"INCOMPLETE_OR_FUTURE_BAR")
  self.assertEqual(parse("AAA",data(30),NOW)["status"],"STALE_TIMESTAMP")
 def test_api_error_does_not_create_baseline(self):
  r=run({"candidates":[{"symbol":"AAA"}]},now=NOW,key="dummy",request=lambda s,k:{"status":"error","message":"quota"})
  self.assertEqual(r["results"][0]["status"],"PROVIDER_ERROR")
  s,x=reconcile({},r)
  self.assertEqual(x["new_baselines"],0)
 def test_cap_and_prioritize(self):
  r=run({"candidates":[{"symbol":"BBB"},{"symbol":"CCC"}]},prior={"symbols":{"AAA":{}}},now=NOW,key="dummy",
        request=lambda s,k:{"status":"error"})
  self.assertEqual(r["results"][0]["symbol"],"AAA")
  self.assertLessEqual(r["requested"],6)
if __name__=="__main__":unittest.main()
