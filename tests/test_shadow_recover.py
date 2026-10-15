import unittest
from radar.shadow_recover import recover

class RecoveryTests(unittest.TestCase):
    def test_excludes_pre_alert_bars(self):
        state = {"ABC": {"first_seen": "2026-10-15T16:48:07+00:00", "first_price": 10}}
        rows = [{"t": "2026-10-15T16:48:00Z", "h": 50},
                {"t": "2026-10-15T16:49:00Z", "h": 12}]
        outcome = recover(state, lambda *_: rows)["ABC"]
        self.assertEqual(outcome["max_bar_high_after"], 12)
        self.assertEqual(outcome["max_pct_after"], 20)
    def test_alert_minute_bar_is_excluded(self):
        state = {"ABC": {"first_seen": "2026-10-15T16:48:07+00:00", "first_price": 10}}
        rows = [{"t": "2026-10-15T16:48:30Z", "h": 50},
                {"t": "2026-10-15T16:49:00Z", "h": 12}]
        self.assertEqual(recover(state, lambda *_: rows)["ABC"]["max_bar_high_after"], 12)

    def test_missing_bars_is_data_gap(self):
        state = {"ABC": {"first_seen": "2026-10-15T16:48:07+00:00", "first_price": 10}}
        self.assertEqual(recover(state, lambda *_: [])["ABC"]["status"], "DATA_GAP")

if __name__ == "__main__":
    unittest.main()
