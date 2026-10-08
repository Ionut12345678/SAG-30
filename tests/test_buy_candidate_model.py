import unittest
from radar.buy_candidate_model import decide

T="2026-10-08T14:00:00+00:00"
GOOD={"latestTrade":{"p":10,"t":T},"latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":T}}
def run(**kw):
 a=dict(snapshot=GOOD,retrieval_ts=T,quality="OK",change_pct=5,
 state="C34R2-HOT-SHADOW",discovery=True,priority=True,observations=2,first_seen_ts=T)
 a.update(kw)
 return decide(**a)
class TestBuyCandidateModel(unittest.TestCase):
 def test_quote_ready_never_live_buy(self):
  r=run();self.assertEqual(r["stage"],"PAPER_REVIEW_ONLY");self.assertFalse(r["live_buy"]);self.assertFalse(r["order_allowed"])
 def test_no_quote_fast_recheck(self):
  r=run(snapshot={});self.assertEqual(r["stage"],"FAST_RECHECK");self.assertFalse(r["paper_review"])
 def test_expired_rejected(self):
  r=run(first_seen_ts="2026-10-08T13:40:00+00:00");self.assertEqual(r["stage"],"REJECT_OR_EXPIRED")
 def test_late_not_paper(self):
  r=run(change_pct=12);self.assertFalse(r["paper_review"])
 def test_undiscovered_not_paper(self):
  r=run(discovery=False,priority=False);self.assertFalse(r["paper_review"])
if __name__=="__main__":unittest.main()
