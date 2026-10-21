import unittest
from datetime import datetime,timedelta,timezone
from radar_historical_replay import replay,summarize

T=datetime(2026,10,20,13,30,tzinfo=timezone.utc)
def bars(prices,volumes=None):
    volumes=volumes or [100]*len(prices)
    return [{"ts":(T+timedelta(minutes=5*i)).isoformat(),
             "open":p,"high":p*1.005,"low":p*0.995,
             "close":p,"volume":v} for i,(p,v) in enumerate(zip(prices,volumes))]
class HistoricalReplayTests(unittest.TestCase):
    def test_winner_uses_next_open_and_future_high_only(self):
        b=bars([10,10.7,10.8,12.0,13.0,15.0])
        r=replay("WIN",b,10)
        self.assertEqual(r["status"],"EVALUATED_HISTORICAL_REPLAY")
        self.assertEqual(r["proxy_entry_price_next_open"],10.8)
        self.assertIn("20",r["hits_from_proxy_entry"])
        self.assertEqual(r["outcome"],"WINNER_20")
    def test_false_winner_is_counted(self):
        r=replay("FALSE",bars([10,10.6,10.7,10.3,10.2]),10)
        self.assertEqual(r["outcome"],"FALSE_WINNER_UNDER_20")
        self.assertEqual(summarize([r])["false_winner_under_20_count"],1)
    def test_signal_bar_peak_is_not_future_profit(self):
        b=bars([10,10.7,10.8,10.6,10.5])
        b[1]["high"]=20
        r=replay("NO_HINDSIGHT",b,10)
        self.assertNotIn("50",r["hits_from_proxy_entry"])
    def test_no_signal_no_cherry_pick(self):
        self.assertEqual(replay("NO",bars([10,11.5,13,15]),10)["status"],"NO_EARLY_WINDOW")
    def test_gap_above_window_is_recorded_as_missed_not_fake_entry(self):
        b=bars([12.0,13.0,15.0,17.0,19.0])
        r=replay("GAP",b,10)
        self.assertEqual(r["status"],"NO_EARLY_WINDOW")
        self.assertTrue(r["gap_above_10pct_at_first_bar"])
        self.assertTrue(r["missed_20pct_runner"])
        self.assertEqual(summarize([r])["missed_20pct_runners_without_5to10_entry"],1)
    def test_malformed_time_rejected(self):
        b=bars([10,10.7,10.8,12])
        b[2]["ts"]=b[1]["ts"]
        self.assertEqual(replay("BAD",b,10)["status"],"INVALID_DATA")
    def test_bad_ohlc_rejected(self):
        b=bars([10,10.7,10.8,12])
        b[2]["low"]=0
        self.assertEqual(replay("BAD",b,10)["status"],"INVALID_DATA")
if __name__=="__main__":unittest.main()
