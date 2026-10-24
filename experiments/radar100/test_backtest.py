import unittest
from datetime import date, timedelta
from backtest import backtest, test_signal

def bars(prices):
    start = date(2025, 1, 1)
    return [{"date": start + timedelta(days=i), "open": p, "high": p*1.01,
             "low": p*.99, "close": p} for i, p in enumerate(prices)]

class Radar100Tests(unittest.TestCase):
    def test_no_signal_on_flat_prices(self):
        result = backtest(bars([100.] * 100))
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["final_eur"], 100.)

    def test_no_future_lookahead_in_signal(self):
        data = bars([100+i for i in range(90)])
        earlier = test_signal(data, 70)
        for row in data[71:]:
            row["close"] *= 0.1
        self.assertEqual(test_signal(data, 70), earlier)

    def test_fee_reduces_result(self):
        data = bars([100+i for i in range(110)])
        gross = backtest(data, cost_bps=0)
        net = backtest(data, cost_bps=20)
        self.assertGreater(gross["trade_count"], 0)
        self.assertLess(net["final_eur"], gross["final_eur"])

    def test_dca_never_increases_budget_cap(self):
        data = bars([100+i for i in range(110)])
        result = backtest(data, dca=True)
        self.assertTrue(all(t["filled_eur"] <= 20.00001 for t in result["trades"]))

if __name__ == "__main__":
    unittest.main()
