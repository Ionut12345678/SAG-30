import unittest
from radar_reverse_engineering import evaluate

def bars(prices):
    return [{"ts":f"2026-10-19T14:{30+i:02d}:00Z","price":p,"volume":100*(i+1)} for i,p in enumerate(prices)]

class ReverseEngineeringTests(unittest.TestCase):
    def test_winner_from_early_entry(self):
        r=evaluate("WIN",bars([10,10.7,11.1,12,13,15.1]))
        self.assertEqual(r["entry_pct_vs_reference"],7.0)
        self.assertIn("30",r["thresholds"])
        self.assertIn("50",r["thresholds"])
        self.assertGreater(r["peak_pct_from_entry"],40)
    def test_false_winner(self):
        r=evaluate("FALSE",bars([10,10.6,10.2,9.5]))
        self.assertEqual(r["thresholds"],{})
        self.assertLess(r["peak_pct_from_entry"],0)
    def test_repeated_timestamp_rejected(self):
        x=bars([10,10.7,12])
        x[2]["ts"]=x[1]["ts"]
        self.assertEqual(evaluate("BAD",x)["status"],"INVALID_SEQUENCE")
    def test_no_entry(self):
        self.assertEqual(evaluate("NONE",bars([10,12,14]))["status"],"NO_5_TO_10_ENTRY")
if __name__=="__main__":
    unittest.main()
