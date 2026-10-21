import unittest
from radar_big_movers_audit import load_csv,audit
class BigMoversAuditTests(unittest.TestCase):
 def test_parse_bom_and_sanitize(self):
  s="\ufeffyear,symbol,gain_pct,low_date,high_date\n2026,AAA,75,2026-01-02,2026-01-10\n2026,BAD!,90,2026-01-01,2026-01-05\n"
  r=load_csv(s)
  self.assertEqual(len(r),1)
  self.assertEqual(r[0]["symbol"],"AAA")
 def test_no_predictions_or_precision_from_winners(self):
  labels=load_csv("year,symbol,gain_pct,low_date,high_date\n2026,AAA,75,2026-01-02,2026-01-10\n")
  annual={"symbols":[{"symbol":"AAA","eligible":True},{"symbol":"BBB","eligible":True}]}
  out=audit(labels,annual)
  self.assertEqual(out["overlap_count"],1)
  self.assertEqual(out["trade_signals"],0)
  self.assertFalse(out["buy_enabled"])
  self.assertIn("positive-only",out["forbidden_uses"][1])
if __name__=="__main__":unittest.main()
