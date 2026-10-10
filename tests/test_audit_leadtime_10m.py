import unittest
from radar.audit_leadtime_10m import evaluate


def event(minute, pct):
    return {"ts": f"2026-10-09T14:{minute:02d}:00Z", "change_pct": pct}


class LeadTimeTest(unittest.TestCase):
    def setUp(self):
        # First observed qualifying acceleration starts at 14:15, not the 14:25 peak.
        self.samples = [event(5, 2), event(10, 2.5), event(15, 2.7),
                        event(20, 8), event(25, 35)]
        self.scout = event(0, 0)

    def test_primary_scout_early_and_watch_early(self):
        result = evaluate(self.scout, self.samples, event(5, 2))
        self.assertEqual(result["status"], "EARLY_10M")
        self.assertEqual(result["lead_minutes"], 15)
        self.assertEqual(result["watch_status"], "EARLY_10M")
        self.assertEqual(result["watch_lead_minutes"], 10)
        self.assertEqual(result["acceleration_onset_ts"], "2026-10-09T14:15:00+00:00")

    def test_late_watch_does_not_erase_early_scout(self):
        result = evaluate(self.scout, self.samples, event(10, 2.5))
        self.assertEqual(result["status"], "EARLY_10M")
        self.assertEqual(result["scout_lead_minutes"], 15)
        self.assertEqual(result["watch_status"], "LATE")
        self.assertEqual(result["watch_lead_minutes"], 5)

    def test_watch_after_onset_missed_but_scout_early(self):
        result = evaluate(self.scout, self.samples, event(23, 20))
        self.assertEqual(result["status"], "EARLY_10M")
        self.assertEqual(result["watch_status"], "MISSED")

    def test_sparse_onset_window_unknown(self):
        self.assertEqual(evaluate(self.scout, [event(20, 8), event(29, 35)],
                                  event(5, 2))["status"], "UNVERIFIABLE")

    def test_scout_to_onset_gap_is_unknown_even_if_watch_has_a_timestamp(self):
        result = evaluate(self.scout, [event(20, 8), event(25, 35)], event(5, 2))
        self.assertEqual(result["status"], "UNVERIFIABLE")
        self.assertEqual(result["reason"], "coverage_gap_scout_to_onset")

    def test_same_cycle_watch_does_not_invalidate_independent_scout(self):
        result = evaluate(self.scout, self.samples, event(15, 2.7))
        self.assertEqual(result["status"], "EARLY_10M")
        self.assertEqual(result["watch_status"], "UNVERIFIABLE")
        self.assertEqual(result["watch_reason"], "same_cycle_watch_onset")

    def test_missing_watch_does_not_invalidate_scout(self):
        result = evaluate(self.scout, self.samples)
        self.assertEqual(result["status"], "EARLY_10M")
        self.assertEqual(result["watch_status"], "UNVERIFIABLE")
        self.assertEqual(result["watch_reason"], "missing_first_watch")

    def test_watch_before_scout_not_credited(self):
        result = evaluate(event(10, 2), self.samples, event(5, 2))
        self.assertEqual(result["status"], "LATE")
        self.assertEqual(result["watch_status"], "UNVERIFIABLE")
        self.assertEqual(result["watch_reason"], "watch_before_scout")

    def test_conflicting_same_timestamp_unknown(self):
        result = evaluate(self.scout, self.samples + [event(20, 10)], event(5, 2))
        self.assertEqual(result["status"], "UNVERIFIABLE")
        self.assertEqual(result["reason"], "conflicting_same_timestamp")

    def test_duplicate_identical_sample_is_not_false_gap(self):
        result = evaluate(self.scout, self.samples + [event(10, 2.5)], event(5, 2))
        self.assertEqual(result["status"], "EARLY_10M")

    def test_no_pre_scout_onset_credit(self):
        result = evaluate(event(26, 35), self.samples, event(26, 35))
        self.assertEqual(result["status"], "UNVERIFIABLE")
        self.assertEqual(result["reason"], "no_observed_acceleration_onset")

    def test_same_cycle_scout_onset_is_unverifiable(self):
        result = evaluate(event(15, 2.7), self.samples, event(15, 2.7))
        self.assertEqual(result["status"], "UNVERIFIABLE")
        self.assertEqual(result["reason"], "same_cycle_scout_onset")


if __name__ == "__main__":
    unittest.main()
