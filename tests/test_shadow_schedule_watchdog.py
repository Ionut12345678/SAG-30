import datetime as dt
import unittest
from radar.shadow_schedule_watchdog import market_window, needs_recovery

UTC = dt.timezone.utc


class WatchdogTests(unittest.TestCase):
    def test_us_daylight_saving_market_window(self):
        for month, day, hour in [(7, 15, 14), (12, 15, 15)]:
            now = dt.datetime(2026, month, day, hour, 0, tzinfo=UTC)
            self.assertTrue(market_window(now))
        self.assertFalse(market_window(dt.datetime(2026, 7, 18, 14, tzinfo=UTC)))

    def test_recent_completed_or_queued_run_prevents_duplicate(self):
        now = dt.datetime(2026, 10, 16, 15, tzinfo=UTC)
        for status in ("completed", "queued", "in_progress"):
            runs = [{"event": "schedule", "status": status,
                     "created_at": "2026-10-16T14:52:00Z"}]
            self.assertFalse(needs_recovery(runs, now))

    def test_old_running_or_queued_scan_is_not_duplicated(self):
        now = dt.datetime(2026, 10, 16, 15, tzinfo=UTC)
        for status in ("queued", "in_progress"):
            runs = [{"event": "schedule", "status": status,
                     "created_at": "2026-10-16T14:10:00Z"}]
            self.assertFalse(needs_recovery(runs, now))

    def test_stale_or_other_workflow_event_requires_recovery(self):
        now = dt.datetime(2026, 10, 16, 15, tzinfo=UTC)
        self.assertTrue(needs_recovery([], now))
        self.assertTrue(needs_recovery([{"event": "schedule",
                                        "created_at": "2026-10-16T14:30:00Z"}], now))
        self.assertTrue(needs_recovery([{"event": "pull_request",
                                        "created_at": "2026-10-16T14:59:00Z"}], now))


if __name__ == "__main__":
    unittest.main()
