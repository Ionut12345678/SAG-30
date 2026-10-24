import unittest
from datetime import datetime, timezone, timedelta
from radar_yahoo_1m_shadow import inspect, run, regular_session_status

class YahooOneMinuteTests(unittest.TestCase):
    def sample(self,stamps,close,volume):
        return {"chart":{"result":[{"meta":{"chartPreviousClose":10},"timestamp":stamps,
            "indicators":{"quote":[{"close":close,"volume":volume}]}}]}}
    def test_weekend_skips_network_and_does_not_claim_data_gap(self):
        now=datetime(2026,10,24,15,0,tzinfo=timezone.utc)
        def forbidden(_):
            raise AssertionError("weekend must not request live bars")
        result=run({"candidates":[{"symbol":"AAPL"}]},now=now,reader=forbidden)
        self.assertEqual(result["status"],"MARKET_CLOSED")
        self.assertEqual(result["records"],[])
        self.assertEqual(inspect("AAPL",{},now)["status"],"MARKET_CLOSED")
    def test_dst_week_transition(self):
        self.assertEqual(regular_session_status(datetime(2026,10,26,13,30,tzinfo=timezone.utc)),"REGULAR_SESSION")
        self.assertEqual(regular_session_status(datetime(2026,11,2,14,30,tzinfo=timezone.utc)),"REGULAR_SESSION")
    def test_recent_completed(self):
        now=datetime(2026,10,22,15,34,30,tzinfo=timezone.utc)
        ts=int(datetime(2026,10,22,15,32,tzinfo=timezone.utc).timestamp())
        obs=inspect("TEST",self.sample([ts],[10.5],[1500]),now)
        self.assertEqual(obs["status"],"RECENT_COMPLETED_BAR_VENDOR_UNVERIFIED")
        self.assertEqual(obs["bar_volume"],1500)
        self.assertFalse(obs["validated_signal"])
    def test_forming_bar_rejected(self):
        now=datetime(2026,10,22,15,34,30,tzinfo=timezone.utc)
        ts=int(datetime(2026,10,22,15,34,tzinfo=timezone.utc).timestamp())
        self.assertEqual(inspect("TEST",self.sample([ts],[10.6],[500]),now)["status"],
                         "NO_COMPLETED_CURRENT_SESSION_BAR")
    def test_old_day_rejected(self):
        now=datetime(2026,10,22,15,34,tzinfo=timezone.utc)
        ts=int(datetime(2026,10,21,15,32,tzinfo=timezone.utc).timestamp())
        self.assertEqual(inspect("TEST",self.sample([ts],[10.6],[500]),now)["status"],
                         "NO_COMPLETED_CURRENT_SESSION_BAR")
    def test_stale_bar_rejected(self):
        now=datetime(2026,10,22,15,34,tzinfo=timezone.utc)
        ts=int(datetime(2026,10,22,15,20,tzinfo=timezone.utc).timestamp())
        self.assertEqual(inspect("TEST",self.sample([ts],[10.6],[500]),now)["status"],"STALE_BAR")

if __name__=="__main__":unittest.main()
