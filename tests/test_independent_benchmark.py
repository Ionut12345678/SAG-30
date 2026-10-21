import unittest
from radar_independent_benchmark import compare

def event(day,group="EARLY_DAILY_5_TO_10",volume=2.0,win=False,low=-5):
 return {"signal_date":day,"group":group,"daily_gap_pct":1,
         "daily_change_pct":7,"volume_ratio_20_prior_days":volume,
         "five_session_min_low_pct":low,"hits_20_pct_upper_bound":win}

class IndependentBenchmarkTests(unittest.TestCase):
 def test_no_lookahead_in_rule_selection(self):
  d={"symbols":[{"symbol":"AAA","eligible":True,"events":[event("2026-01-03",win=False)]}]}
  a=compare(d)
  d["symbols"][0]["events"][0]["hits_20_pct_upper_bound"]=True
  b=compare(d)
  self.assertEqual(a["results"]["holdout"]["early_rvol_1_5"]["signals"],
                   b["results"]["holdout"]["early_rvol_1_5"]["signals"])
  self.assertNotEqual(a["results"]["holdout"]["early_rvol_1_5"]["upper_bound_hit_20"],
                      b["results"]["holdout"]["early_rvol_1_5"]["upper_bound_hit_20"])
 def test_training_never_leaks_to_holdout(self):
  items=[event("2025-12-30",win=True),event("2026-01-03",win=False)]
  r=compare({"symbols":[{"symbol":"AAA","eligible":True,"events":items}]})
  self.assertEqual(r["results"]["train"]["baseline_all"]["upper_bound_hit_20"],1)
  self.assertEqual(r["results"]["holdout"]["baseline_all"]["upper_bound_hit_20"],0)
 def test_low_volume_rejected_from_filter_but_in_baseline(self):
  r=compare({"symbols":[{"symbol":"AAA","eligible":True,"events":[event("2026-01-03",volume=0.5)]}]})
  self.assertEqual(r["results"]["holdout"]["baseline_all"]["signals"],1)
  self.assertEqual(r["results"]["holdout"]["early_rvol_1_5"]["signals"],0)
 def test_absence_does_not_invent_success(self):
  r=compare({"symbols":[]})
  self.assertIsNone(r["results"]["holdout"]["baseline_all"]["upper_bound_hit_rate_pct"])
  self.assertFalse(r["intraday_validated"])
  self.assertFalse(r["winning_rule_selected"])
if __name__=="__main__":unittest.main()
