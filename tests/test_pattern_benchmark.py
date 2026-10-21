import unittest
from copy import deepcopy
from radar_pattern_benchmark import classify,benchmark

def case(symbol,vol,change=7,win=False):
 return {"symbol":symbol,"session":"2026-10-20",
  "status":"EVALUATED_HISTORICAL_REPLAY",
  "signal_volume_ratio_vs_prior_6":vol,"signal_change_pct":change,
  "outcome":"WINNER_20" if win else "FALSE_WINNER_UNDER_20",
  "max_gain_from_proxy_entry_pct":30 if win else 4,
  "hits_from_proxy_entry":{"20":{}} if win else {}}
class PatternTests(unittest.TestCase):
 def test_fixed_rule_pass_and_reject(self):
  self.assertEqual(classify(case("A",2.1,7)),"PASS")
  self.assertEqual(classify(case("B",1.9,7)),"REJECT")
  self.assertEqual(classify(case("C",2.5,9)),"REJECT")
 def test_future_outcome_cannot_change_decision(self):
  a=case("A",2.2,6)
  b=deepcopy(a)
  b["outcome"]="WINNER_20"
  b["max_gain_from_proxy_entry_pct"]=100
  b["hits_from_proxy_entry"]={"50":{"bar_start_utc":"tomorrow"}}
  self.assertEqual(classify(a),classify(b))
 def test_missing_pre_entry_volume_abstains(self):
  self.assertEqual(classify(case("A",None)),"INSUFFICIENT_PRE_ENTRY_VOLUME")
  self.assertEqual(benchmark([case("A",None)])["feature_evaluable"],0)
 def test_all_false_winners_does_not_claim_success(self):
  report=benchmark([case("A",3),case("B",1)])
  self.assertEqual(report["experimental_hit_20_count"],0)
  self.assertTrue(report["insufficient_to_select_model"])
  self.assertIsNone(report["winner_capture_pct"])
 def test_population_separated_from_available_features(self):
  report=benchmark([case("A",3,win=True),case("B",None),
                    {"symbol":"X","status":"NO_EARLY_WINDOW"}])
  self.assertEqual(report["population"],3)
  self.assertEqual(report["feature_evaluable"],1)
  self.assertEqual(report["baseline_hit_20_count"],1)
  self.assertEqual(report["winner_capture_pct"],100)
if __name__=="__main__":unittest.main()
