import datetime as dt
import unittest
from radar.shadow_tplus import evaluate

UTC = dt.timezone.utc


class TPlusTests(unittest.TestCase):
    def test_observed_sessions(self):
        tracked = {"ABC": {"first_seen": "2026-10-16T15:00:00Z", "first_price": 10}}
        def fetch(*_):
            return [{"t": "2026-10-19T20:00:00Z", "h": 11},
                    {"t": "2026-10-20T20:00:00Z", "h": 12}]
        result = evaluate(tracked, fetch, dt.datetime(2026, 10, 20, 23, tzinfo=UTC))
        x = result["outcomes"]["ABC"]
        self.assertEqual(x["T+1"]["max_pct"], 10)
        self.assertEqual(x["T+2"]["max_pct"], 20)
        self.assertEqual(x["T+5"]["status"], "NOT_MEASURED")

    def test_missing_session_cannot_shift_tplus(self):
        tracked = {"ABC": {"first_seen": "2026-10-16T15:00:00Z", "first_price": 10}}
        def fetch(*_):
            return [{"t": "2026-10-20T20:00:00Z", "h": 12}]
        x = evaluate(tracked, fetch, dt.datetime(2026, 10, 20, 23, tzinfo=UTC))["outcomes"]["ABC"]
        self.assertEqual(x["T+1"]["status"], "NOT_MEASURED")

    def test_failed_feed_is_gap_not_zero(self):
        tracked = {"ABC": {"first_seen": "2026-10-16T15:00:00Z", "first_price": 10}}
        def fail(*_):
            raise TimeoutError()
        x = evaluate(tracked, fail, dt.datetime(2026, 10, 20, 23, tzinfo=UTC))["outcomes"]["ABC"]
        self.assertEqual(x["T+1"]["status"], "DATA_GAP")


if __name__ == "__main__":
    unittest.main()
