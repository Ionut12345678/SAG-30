import unittest
from radar.paper_outcome_v03 import evaluate
class TestPaperOutcome(unittest.TestCase):
 def test_future_only(self):
  r=evaluate(10,"2026-10-09T14:00:00Z",[
   {"ts":"2026-10-09T13:59:00Z","price":100},
   {"ts":"2026-10-09T14:01:00Z","price":11},
   {"ts":"2026-10-09T14:02:00Z","price":10.5}])
  self.assertEqual(r["max_future_observed_price"],11)
  self.assertEqual(r["net_max_after_assumed_cost_pct"],8)
  self.assertFalse(r["not_buy"] is False)
 def test_no_future_censored(self):
  self.assertEqual(evaluate(10,"2026-10-09T14:00:00Z",[])["status"],"CENSORED_NO_FUTURE_PRINTS")
 def test_invalid_ask(self):
  self.assertEqual(evaluate(0,"2026-10-09T14:00:00Z",[])["status"],"INVALID_ENTRY")
if __name__=="__main__":unittest.main()
