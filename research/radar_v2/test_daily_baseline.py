import unittest
from research.radar_v2.daily_baseline import backtest

class TestDailyBaseline(unittest.TestCase):
    def test_no_future_in_signal(self):
        bars=[{"symbol":"A","source_ts":str(i),"close":100+i,"volume":1000} for i in range(10)]
        result=backtest(bars,lookback=2,horizon=2,threshold=0.01)
        self.assertGreater(result["signal_count"],0)
        self.assertEqual(result["signals"][0]["signal_ts"],"2")

    def test_insufficient_history(self):
        bars=[{"symbol":"A","source_ts":str(i),"close":100+i,"volume":1000} for i in range(3)]
        self.assertEqual(backtest(bars,lookback=2,horizon=2)["signal_count"],0)

    def test_duplicate_timestamp_fails(self):
        bars=[{"symbol":"A","source_ts":"1","close":100,"volume":100},
              {"symbol":"A","source_ts":"1","close":101,"volume":100}]
        with self.assertRaises(ValueError):backtest(bars,lookback=1,horizon=0)
