import unittest
from radar.audit_leadtime_10m import evaluate

class LeadTimeTest(unittest.TestCase):
    def test_early_and_late(self):
        samples=[{"ts":"2026-10-09T14:20:00Z","change_pct":8},
                 {"ts":"2026-10-09T14:25:00Z","change_pct":35}]
        self.assertEqual(evaluate({"ts":"2026-10-09T14:05:00Z","change_pct":2},samples)["status"],"EARLY_10M")
        self.assertEqual(evaluate({"ts":"2026-10-09T14:15:00Z","change_pct":2},samples)["status"],"LATE")
    def test_no_lookahead_credit_for_detection_after_onset(self):
        samples=[{"ts":"2026-10-09T14:20:00Z","change_pct":8},
                 {"ts":"2026-10-09T14:25:00Z","change_pct":35}]
        self.assertEqual(evaluate({"ts":"2026-10-09T14:23:00Z","change_pct":20},samples)["status"],"MISSED")
    def test_sparse_data_unverifiable(self):
        samples=[{"ts":"2026-10-09T14:20:00Z","change_pct":8},
                 {"ts":"2026-10-09T14:29:00Z","change_pct":35}]
        self.assertEqual(evaluate({"ts":"2026-10-09T14:00:00Z","change_pct":2},samples)["status"],"UNVERIFIABLE")
if __name__=="__main__":
    unittest.main()
