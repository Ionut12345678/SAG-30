import unittest
from datetime import datetime,timezone
from radar.matched_baseline import compare
NOW=datetime(2026,10,13,12,tzinfo=timezone.utc)

def point(sym,minute,pct,selected=0,session="2026-10-12"):
    return {"symbol":sym,"session":session,"retrieval_ts":f"2026-10-12T18:{minute:02d}:00Z",
            "change_pct":pct,"selected":selected,"run_id":minute}

class MatchedBaselineTests(unittest.TestCase):
    def test_early_baseline_and_sag30_both_hit(self):
        x=compare([point("A",0,6,1),point("A",5,35),point("A",10,55)],NOW)
        self.assertEqual(x["rules"]["BASELINE_5_TO_10"]["observed_later_50"],1)
        self.assertEqual(x["rules"]["SAG30_SELECTED_UNDER_10"]["observed_later_50"],1)

    def test_first_seen_already_above_30_is_never_early_hit(self):
        x=compare([point("A",0,45,1),point("A",5,65)],NOW)
        self.assertEqual(x["winner_sessions_30"],1)
        self.assertEqual(x["rules"]["SAG30_SELECTED_UNDER_10"]["alerts"],0)

    def test_same_timestamp_has_no_later_target_credit(self):
        x=compare([point("A",0,5,1),point("A",0,50,0)],NOW)
        self.assertEqual(x["rules"]["SAG30_SELECTED_UNDER_10"]["observed_later_50"],0)

    def test_false_positive_in_denominator(self):
        x=compare([point("A",0,5,1),point("A",5,6),
                   point("B",0,6,0),point("B",5,31)],NOW)
        self.assertEqual(x["rules"]["BASELINE_5_TO_10"]["alerts"],2)
        self.assertEqual(x["rules"]["BASELINE_5_TO_10"]["observed_later_30"],1)
        self.assertEqual(x["rules"]["SAG30_SELECTED_UNDER_10"]["observed_later_30"],0)

    def test_open_session_excluded(self):
        x=compare([point("A",0,5,1,session="2026-10-13")],NOW)
        self.assertEqual(x["eligible_symbol_sessions"],0)

if __name__=="__main__":
    unittest.main()
