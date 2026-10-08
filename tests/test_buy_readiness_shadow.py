"""Regression tests: SHADOW BUY readiness cannot authorize an order."""
import unittest
from radar.buy_readiness_shadow import evaluate

class TestBuyReadinessShadow(unittest.TestCase):
 def test_discovered_without_quote_is_blocked(self):
  r=evaluate({},"2026-10-08T14:00:00+00:00","OK",5,"C34R2-HOT-SHADOW",True,True)
  self.assertEqual(r["stage"],"BLOCKED_ACTIONABILITY")
  self.assertFalse(r["buy_approved"])
  self.assertFalse(r["order_allowed"])
 def test_quote_pass_still_not_buy(self):
  ts="2026-10-08T14:00:00+00:00"
  snap={"latestTrade":{"p":10,"t":ts},"latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":ts}}
  r=evaluate(snap,ts,"OK",5,"C34R2-HOT-SHADOW",True,True)
  self.assertEqual(r["stage"],"ENTRY_READY_SHADOW_UNVALIDATED")
  self.assertFalse(r["buy_approved"])
  self.assertFalse(r["order_allowed"])
 def test_non_discovery_not_promoted(self):
  ts="2026-10-08T14:00:00+00:00"
  snap={"latestTrade":{"p":10,"t":ts},"latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":ts}}
  r=evaluate(snap,ts,"OK",5,"C34R2-HOT-SHADOW",False,False)
  self.assertEqual(r["stage"],"QUOTE_PASS_NOT_DISCOVERED")
  self.assertFalse(r["buy_approved"])
if __name__=="__main__":unittest.main()
