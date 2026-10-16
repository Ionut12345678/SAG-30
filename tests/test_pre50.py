import unittest
from radar.pre50 import evaluate, backtest, scan, resolve
from radar.pre50_fetch import valid_ohlcv


def bars(n=50, volume=100000):
    rows = []
    for i in range(n):
        close = 9.0 + i * 0.01
        rows.append({"date": f"2026-09-{i+1:02d}", "open": close - .02,
                     "high": close + .10, "low": close - .10,
                     "close": close, "volume": volume})
    return rows


class Pre50Tests(unittest.TestCase):
    def test_eligibility_requires_40_rows(self):
        rows = bars()
        self.assertIsNone(evaluate(rows, 39))
        self.assertIsNotNone(evaluate(rows, 40))

    def test_next_session_target_not_same_day(self):
        rows = bars(50)
        rows[41]["high"] = 15.0
        report = backtest({"AAA": rows})
        self.assertEqual(report["totals"]["eligible"], 9)
        self.assertEqual(report["totals"]["events"], 1)

    def test_no_future_data_leakage(self):
        rows = bars(51)
        first = evaluate(rows, 40)
        rows[41]["high"] = 99.0
        self.assertEqual(evaluate(rows, 40), first)

    def test_exclude_already_exploded(self):
        rows = bars()
        rows[40]["close"] = rows[39]["close"] * 1.85
        rows[40]["high"] = rows[40]["close"] + .1
        self.assertIsNone(evaluate(rows, 40))

    def test_resolution_uses_first_subsequent_session(self):
        rows = bars()
        rows[41]["high"] = 15.0
        journal = [{"symbol": "AAA", "date": rows[40]["date"],
                    "close": rows[40]["close"], "resolved": None}]
        resolved = resolve(journal, {"AAA": rows})
        self.assertTrue(resolved[0]["resolved"]["hit_50"])
        self.assertFalse(resolved[0]["resolved"]["high_is_executable"])

    def test_yahoo_invalid_daily_ohlcv_rejected(self):
        self.assertTrue(valid_ohlcv([9, 10, 8, 9.5, 100]))
        self.assertFalse(valid_ohlcv([9, 10, 8, float('nan'), 100]))
        self.assertFalse(valid_ohlcv([9, 10, 8, float('inf'), 100]))
        self.assertFalse(valid_ohlcv([9, 10, 8, 11, 100]))

    def test_scan_shadow_no_buy(self):
        report = scan({"AAA": bars()})
        self.assertFalse(report["buy"])
        self.assertEqual(report["mode"], "SHADOW_ONLY")


if __name__ == "__main__":
    unittest.main()
