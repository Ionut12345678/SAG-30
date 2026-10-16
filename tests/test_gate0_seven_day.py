import datetime as dt
import unittest
from radar.gate0_seven_day import evaluate

UTC = dt.timezone.utc


class SevenDayGateTests(unittest.TestCase):
    def setUp(self):
        self.start = dt.datetime(2026, 10, 16, tzinfo=UTC)
        self.end = self.start + dt.timedelta(days=7)

    def test_no_scans_does_not_mean_zero_candidates(self):
        result = evaluate({"tracked": {}}, {"outcomes": {}}, [],
                          self.start, self.start, self.end)
        self.assertEqual(result["gate"], "HOLD")
        self.assertIsNone(result["cadence_coverage_pct"])
        self.assertIsNone(result["followup_coverage_pct"])

    def test_missing_followup_is_not_a_zero_return(self):
        state = {"tracked": {"TEST": {"first_seen": "2026-10-16T15:00:00Z",
                                        "first_price": 10}}}
        result = evaluate(state, {"outcomes": {}}, [], self.start, self.start, self.end)
        self.assertIsNone(result["signals"][0]["observed_4h_max_pct"])
        self.assertEqual(result["signals"][0]["t_plus_5"], "NOT_MEASURED")
        self.assertEqual(result["followup_coverage_pct"], 0)

    def test_historical_signals_are_not_counted_as_new(self):
        state = {"tracked": {"OLD": {"first_seen": "2026-10-15T15:00:00Z",
                                       "first_price": 10}}}
        result = evaluate(state, {"outcomes": {}}, [], self.start, self.start, self.end)
        self.assertEqual(result["signal_count"], 0)


if __name__ == "__main__":
    unittest.main()
