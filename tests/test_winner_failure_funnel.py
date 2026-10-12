import unittest
from radar.winner_failure_funnel import audit

def winner(symbol,stage,earlier=None):
    return {"symbol":symbol,"session":"2026-10-12",
            "classification_under_10":stage,
            "first_30_ts":"2026-10-12T18:00:00Z",
            "first_under_10_scout_ts":earlier}
class WinnerFailureFunnelTests(unittest.TestCase):
    def test_scout_miss_cause_remains_unresolved(self):
        r=audit({"winners":[winner("A","SCOUT_MISS")]})
        self.assertEqual(r["scout_miss_causes_unresolved"],1)
        self.assertEqual(r["scout_miss_causes_known"],0)
        self.assertEqual(r["records"][0]["coverage_cause"],"UNRESOLVED")
    def test_valid_funnel(self):
        r=audit({"winners":[winner("A","SCOUT_MISS"),
                            winner("B","EARLY_HOT_SUCCESS","2026-10-12T17:00:00Z")]})
        self.assertEqual(r["status"],"RETROSPECTIVE_DIAGNOSTIC_ONLY")
        self.assertEqual(r["classification_counts"]["EARLY_HOT_SUCCESS"],1)
    def test_no_backdated_scout(self):
        r=audit({"winners":[winner("A","MODEL_MISS","2026-10-12T19:00:00Z")]})
        self.assertEqual(r["status"],"REQUIRES_REVIEW")
    def test_duplicate_protected(self):
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            audit({"winners":[winner("A","SCOUT_MISS"),winner("A","SCOUT_MISS")]})
    def test_invalid_stage_protected(self):
        r=audit({"winners":[winner("A","UNEXPECTED")]})
        self.assertEqual(r["status"],"REQUIRES_REVIEW")
    def test_claimed_aggregate_checked(self):
        r=audit({"winners":[winner("A","SCOUT_MISS")],
                 "classification_counts_under_10":{"SCOUT_MISS":0}})
        self.assertEqual(r["status"],"REQUIRES_REVIEW")
if __name__=="__main__":
    unittest.main()
