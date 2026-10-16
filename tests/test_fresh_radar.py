import unittest
from datetime import datetime, timedelta, timezone

from radar.fresh_radar import observe


def snapshot(price, close, ts):
    return {"latestTrade": {"p": price, "t": ts.isoformat()},
            "prevDailyBar": {"c": close}}


class FreshRadarTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)

    def test_only_recent_candidates_are_emitted(self):
        snaps = {
            "RECENT": snapshot(10.7, 10, self.now - timedelta(seconds=30)),
            "STALE": snapshot(10.8, 10, self.now - timedelta(seconds=200)),
        }
        state, report = observe(self.now, list(snaps), snaps)
        self.assertEqual(report["status"], "OBSERVED")
        self.assertEqual(report["new_watches"], 1)
        self.assertIn("RECENT", state["tracked"])
        self.assertNotIn("STALE", state["tracked"])

    def test_subsequent_price_only_not_same_candle_high(self):
        s1 = {"AAA": snapshot(10.6, 10, self.now - timedelta(seconds=10))}
        state, _ = observe(self.now, ["AAA"], s1)
        state2, _ = observe(self.now + timedelta(seconds=20), ["AAA"], s1, state)
        self.assertIsNone(state2["tracked"]["AAA"]["max_post_price"])
        later = self.now + timedelta(minutes=2)
        state3, report = observe(later, ["AAA"], {"AAA": snapshot(15.1, 10, later - timedelta(seconds=10))}, state2)
        self.assertEqual(state3["tracked"]["AAA"]["max_post_price"], 15.1)
        self.assertEqual(state3["tracked"]["AAA"]["milestones"], [15, 20, 30, 50])
        self.assertEqual(len([x for x in report["new_events"] if x["type"] == "POST_ALERT_MILESTONE"]), 4)

    def test_no_double_counting_of_same_trade(self):
        snap = {"AAA": snapshot(10.6, 10, self.now - timedelta(seconds=10))}
        state, _ = observe(self.now, ["AAA"], snap)
        later = self.now + timedelta(minutes=1)
        new = {"AAA": snapshot(12, 10, later - timedelta(seconds=10))}
        state, _ = observe(later, ["AAA"], new, state)
        state, report = observe(later + timedelta(seconds=20), ["AAA"], new, state)
        self.assertEqual(report["new_events"], [])

    def test_missing_data_not_negative(self):
        state, report = observe(self.now, ["AAA"], {})
        self.assertEqual(report["status"], "DATA_GAP")
        self.assertEqual(report["fresh_snapshots"], 0)

    def test_partial_coverage_is_observed_not_success_masquerade(self):
        state, report = observe(self.now, ["AAA", "BBB"], {"AAA": snapshot(10.6, 10, self.now)})
        self.assertEqual(report["status"], "PARTIAL_OBSERVED")
        self.assertEqual(report["coverage"], 0.5)


if __name__ == "__main__":
    unittest.main()
