import unittest
from datetime import date,timedelta
import portfolio

def build(prices,lows=None):
    first=date(2025,1,1)
    return [{"date":first+timedelta(days=i),"open":p,"high":p*1.01,
             "low":(lows[i] if lows is not None else p*.99),"close":p}
             for i,p in enumerate(prices)]

class PortfolioAudit(unittest.TestCase):
    def test_entry_day_stop_executed(self):
        prices=[100+i*.2 for i in range(64)]
        lows=[p*.99 for p in prices]
        lows[61]=prices[61]*.90
        b=build(prices,lows)
        old=portfolio.test_signal
        try:
            portfolio.test_signal=lambda bars,i:i==60
            r=portfolio.simulate({"TEST":b},start="2025-01-01",stop=.05)
        finally:
            portfolio.test_signal=old
        self.assertEqual(r["closed_trades"],1)
        self.assertEqual(r["trades"][0]["reason"],"stop")
        self.assertEqual(r["trades"][0]["entry_date"],r["trades"][0]["exit_date"])

    def test_no_exposure_without_entry(self):
        r=portfolio.simulate({"FLAT":build([100.]*70)})
        self.assertEqual(r["closed_trades"],0)
        self.assertEqual(r["average_exposure_pct"],0)

    def test_reject_bad_settings(self):
        with self.assertRaises(ValueError):
            portfolio.simulate({"X":build([100.]*70)},stop=0)

if __name__=="__main__":unittest.main()
