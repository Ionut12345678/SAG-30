import datetime as dt
import unittest
from radar.gate0_cadence import eligible_slots, audit

UTC = dt.timezone.utc


class CadenceAuditTests(unittest.TestCase):
    def test_dst_changes_utc_start(self):
        before = eligible_slots(dt.datetime(2026, 10, 16, tzinfo=UTC),
                                dt.datetime(2026, 10, 17, tzinfo=UTC))
        after = eligible_slots(dt.datetime(2026, 11, 2, tzinfo=UTC),
                               dt.datetime(2026, 11, 3, tzinfo=UTC))
        self.assertEqual(before[0].hour, 13)
        self.assertEqual(after[0].hour, 14)

    def test_missing_run_is_not_zero_candidates(self):
        start = dt.datetime(2026, 10, 16, tzinfo=UTC)
        end = start + dt.timedelta(days=1)
        result = audit([], start, end)
        self.assertEqual(result["matched_slots"], 0)
        self.assertGreater(result["missing_slots"], 0)
        self.assertEqual(result["coverage_pct"], 0)

    def test_one_run_cannot_cover_multiple_slots(self):
        start = dt.datetime(2026, 10, 16, tzinfo=UTC)
        end = start + dt.timedelta(days=1)
        run = {"event": "schedule", "created_at": "2026-10-16T13:35:00Z", "id": 1}
        result = audit([run], start, end)
        self.assertEqual(result["matched_slots"], 1)


if __name__ == "__main__":
    unittest.main()
