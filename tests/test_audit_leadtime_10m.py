import unittest
from radar.audit_leadtime_10m import evaluate


def event(minute, pct):
    return {"ts": f"2026-10-09T14:{minute:02d}:00Z", "change_pct": pct}


class LeadTimeTest(unittest.TestCase):
    def setUp(self):
        # Earliest >=20% / <=10m interval begins at 14:15, NOT 14:25 peak.
        self.samples = [event(5, 2), event(10, 2.5), event(15, 2.7),
                        event(20, 8), event(25, 35)]
        self.scout = event(0, 0)

    def test_early_watch_to_onset(self):
        result = evaluate(self.scout, self.samples, event(5, 2))
        self.assertEqual(result["status"], "EARLY_10M")
        self.assertEqual(result["lead_minutes"], 10)
        self.assertEqual(result["acceleration_onset_ts"], "2026-10-09T14:15:00+00:00")

    def test_scout_lead_is_not_watch_lead(self):
        result = evaluate(self.scout, self.samples, event(10, 2.5))
        self.assertEqual(result["status"], "LATE")
        self.assertEqual(result["lead_minutes"], 5)
        self.assertEqual(result["scout_lead_minutes"], 15)

    def test_watch_after_onset_is_missed(self):
        result = evaluate(self.scout, self.samples, event(23, 20))
        self.assertEqual(result["status"], "MISSED")

    def test_sparse_onset_window_unknown(self):
        samples = [event(20, 8), event(29, 35)]
        self.assertEqual(evaluate(self.scout, samples, event(5, 2))["status"], "UNVERIFIABLE")

    def test_sparse_watch_to_onset_unknown(self):
        samples = [event(20, 8), event(25, 35)]
        result = evaluate(self.scout, samples, event(5, 2))
        self.assertEqual(result["status"], "UNVERIFIABLE")
        self.assertEqual(result["reason"], "coverage_gap_watch_to_onset")

    def test_same_cycle_watch_onset_unknown(self):
        result = evaluate(self.scout, self.samples, event(15, 2.7))
        self.assertEqual(result["status"], "UNVERIFIABLE")
        self.assertEqual(result["reason"], "same_cycle_watch_onset")

    def test_missing_watch_unknown(self):
        result = evaluate(self.scout, self.samples)
        self.assertEqual(result["status"], "UNVERIFIABLE")
        self.assertEqual(result["reason"], "missing_first_watch")

    def test_watch_before_scout_unknown(self):
        self.assertEqual(evaluate(event(10, 2), self.samples, event(5, 2))["reason"],
                         "watch_before_scout")

    def test_conflicting_same_timestamp_unknown(self):
        result = evaluate(self.scout, self.samples + [event(20, 10)], event(5, 2))
        self.assertEqual(result["reason"], "conflicting_same_timestamp")

    def test_duplicate_identical_sample_is_not_false_gap(self):
        result = evaluate(self.scout, self.samples + [event(10, 2.5)], event(5, 2))
        self.assertEqual(result["status"], "EARLY_10M")


if __name__ == "__main__":
    unittest.main()
