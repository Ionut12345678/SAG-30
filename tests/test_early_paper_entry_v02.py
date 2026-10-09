import unittest
from radar.early_paper_entry_v02 import evaluate
T="2026-10-09T13:00:00+00:00"
Q={"latestTrade":{"p":10,"t":T},"latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":T}}
def run(**changes):
 kw=dict(snapshot=Q,retrieval_ts=T,quality="OK",change_pct=5,discovery=True,priority=True,first_seen_ts=T)
 kw.update(changes)
 return evaluate(**kw)
class TestEarlyPaperV02(unittest.TestCase):
 def test_extended_hours_can_pass_without_hot(self):
  r=run();self.assertEqual(r["stage"],"EARLY_PAPER_ENTRY_REVIEW");self.assertEqual(r["session"],"EXTENDED");self.assertFalse(r["live_buy"])
 def test_missing_quote_never_passes(self):
  self.assertFalse(run(snapshot={})["paper_review"])
 def test_expired_never_passes(self):
  self.assertFalse(run(first_seen_ts="2026-10-09T12:30:00+00:00")["paper_review"])
 def test_late_never_passes(self):
  self.assertFalse(run(change_pct=12)["paper_review"])
 def test_undiscovered_never_passes(self):
  self.assertFalse(run(discovery=False)["paper_review"])
 def test_wide_spread_never_passes(self):
  q={"latestTrade":{"p":10,"t":T},"latestQuote":{"bp":9.2,"ap":10.01,"bs":100,"as":100,"t":T}}
  self.assertFalse(run(snapshot=q)["paper_review"])
if __name__=="__main__":unittest.main()
