import unittest
from datetime import datetime, timezone, timedelta
from radar_vendor_followup import update

class FirstSeenPriceTests(unittest.TestCase):
    def test_milestones_use_first_observed_price_not_reference_close(self):
        t=datetime(2026,10,22,15,0,tzinfo=timezone.utc)
        def report(now,bar,price):
            return {"checked_at_utc":now.isoformat(),"records":[{"symbol":"TEST","status":"RECENT_COMPLETED_BAR_VENDOR_UNVERIFIED","source_timestamp_utc":bar.isoformat(),"price":price,"reference_close":10,"bar_volume":100}]}
        state,_=update({},report(t,t-timedelta(minutes=2),10.6))
        state,dup=update(state,report(t+timedelta(seconds=30),t-timedelta(minutes=2),10.6))
        self.assertEqual(dup["events"],[])
        state,_=update(state,report(t+timedelta(minutes=5),t+timedelta(minutes=2),12))
        item=next(iter(state["vendor_bar_ledger"].values()))
        self.assertEqual(item["later_reported_milestones"],[])
        self.assertEqual(item["max_later_price"],12)
        state,_=update(state,report(t+timedelta(minutes=8),t+timedelta(minutes=6),12.72))
        self.assertEqual(item["later_reported_milestones"],[15,20])
        state,_=update(state,report(t+timedelta(minutes=11),t+timedelta(minutes=9),11))
        self.assertEqual(item["min_price_after_max"],11)
        self.assertEqual(item["later_observations"],3)
        self.assertEqual(item["first_price"],10.6)
    def test_nonfinite_price_rejected(self):
        t=datetime(2026,10,22,15,0,tzinfo=timezone.utc)
        state,summary=update({},{"checked_at_utc":t.isoformat(),"records":[{"symbol":"BAD","status":"RECENT_COMPLETED_BAR_VENDOR_UNVERIFIED","source_timestamp_utc":t.isoformat(),"price":"NaN","reference_close":10,"bar_volume":100}]})
        self.assertEqual(summary["tracked_vendor_candidates"],0)
if __name__=="__main__":unittest.main()
