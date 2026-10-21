import unittest
from datetime import datetime,timedelta,timezone
from radar_premarket_replay import evaluate,summarize
T=datetime(2026,10,20,12,0,tzinfo=timezone.utc)
def bar(i,price):
    ts=(T+timedelta(minutes=5*i)).isoformat()
    return {"ts":ts,"open":price,"high":price*1.005,"low":price*0.995,"close":price,"volume":100}
class PremarketTests(unittest.TestCase):
    def test_early_watch_and_later_regular_peak(self):
        pre=[bar(i,p) for i,p in enumerate([10.1,10.4,10.7,11.0])]
        regular=[bar(20+i,p) for i,p in enumerate([11.1,12,13.5,14])]
        r=evaluate("AAA",10,pre,regular)
        self.assertEqual(r["status"],"EVALUATED_PREMARKET_SHADOW")
        self.assertEqual(r["proxy_entry_price"],10.7)
        self.assertTrue(r["regular_hit_20"])
        self.assertFalse(r["buy_enabled"])
    def test_no_hindsight_same_signal_high(self):
        pre=[bar(i,p) for i,p in enumerate([10.1,10.4,10.5])]
        pre[1]["high"]=30
        reg=[bar(i+20,10.8) for i in range(4)]
        r=evaluate("AAA",10,pre,reg)
        self.assertNotEqual(r["peak_after_signal_pct"],200)
        self.assertFalse(r["regular_hit_20"])
    def test_gap_over_ten_is_abstention(self):
        pre=[bar(i,p) for i,p in enumerate([11.5,12,13])]
        r=evaluate("AAA",10,pre,[bar(i+20,12) for i in range(4)])
        self.assertEqual(r["status"],"ALREADY_OVER_10_AT_FIRST_PREMARKET_BAR")
        self.assertEqual(summarize([r])["already_over_10_at_first_bar"],1)
    def test_missing_adjacent_bar_skips_entry(self):
        pre=[bar(0,10.0),bar(1,10.5),bar(4,10.8)]
        reg=[bar(i+20,11) for i in range(4)]
        self.assertEqual(evaluate("AAA",10,pre,reg)["status"],"MISSING_ADJACENT_ENTRY_BAR")
    def test_no_premarket_samples(self):
        self.assertEqual(evaluate("AAA",10,[],[])["status"],"INSUFFICIENT_PREMARKET")
if __name__=="__main__":unittest.main()
