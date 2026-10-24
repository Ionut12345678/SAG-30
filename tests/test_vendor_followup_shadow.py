import unittest
from datetime import datetime, timezone, timedelta
from radar_vendor_followup import update

def data(now,ts,price):
 return {"checked_at_utc":now.isoformat(),"records":[{"symbol":"TEST","status":"RECENT_COMPLETED_BAR_VENDOR_UNVERIFIED","source_timestamp_utc":ts.isoformat(),"price":price,"reference_close":10,"bar_volume":123}]}

class VendorProspectiveTests(unittest.TestCase):
 def test_only_future_observed_bars_count(self):
  a=datetime(2026,10,22,15,0,tzinfo=timezone.utc)
  state,first=update({},data(a,a-timedelta(minutes=2),10.6))
  self.assertEqual(len(first["events"]),1)
  state,same=update(state,data(a+timedelta(seconds=20),a-timedelta(minutes=2),10.6))
  self.assertEqual(len(same["events"]),0)
  state,follow=update(state,data(a+timedelta(minutes=4),a+timedelta(minutes=1),12.0))
  self.assertEqual(len(follow["events"]),1)
  record=next(iter(state["vendor_bar_ledger"].values()))
  self.assertEqual(record["later_reported_milestones"],[])\n  self.assertEqual(record["max_later_price"],12.0)
  self.assertEqual(follow["validated_signals"],0)
 def test_prior_bar_never_backfills_win(self):
  a=datetime(2026,10,22,15,0,tzinfo=timezone.utc)
  state,_=update({},data(a,a-timedelta(minutes=2),10.6))
  state,other=update(state,data(a+timedelta(minutes=4),a-timedelta(minutes=1),13.0))
  self.assertEqual(other["events"],[])
if __name__=="__main__":unittest.main()
