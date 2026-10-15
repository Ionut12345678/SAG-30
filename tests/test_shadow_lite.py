import unittest
from datetime import datetime, timedelta, timezone
from radar.shadow_lite import cycle, market_window, valid_price

NOW = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)


def snapshot(price, minutes=0):
    return {"latestTrade": {"p": price, "t": (NOW + timedelta(minutes=minutes)).isoformat()},
            "prevDailyBar": {"c": 10.0}}


class ShadowLiteTests(unittest.TestCase):
    def test_prospective_first_seen_and_no_retroactive_outcome(self):
        state, report = cycle(NOW, ["AAA"], {"AAA": snapshot(10.7)}, {})
        self.assertEqual(len(report["new_watch"]), 1)
        self.assertEqual(state["tracked"]["AAA"]["first_seen"], NOW.isoformat())
        self.assertIsNone(state["tracked"]["AAA"]["max_observed_price_after"])
        self.assertFalse(report["buy"])
        self.assertEqual(report["new_events"][0]["decision"], "SHADOW_WATCH_NOT_BUY")

    def test_only_newer_source_after_detection_counts(self):
        state, _ = cycle(NOW, ["AAA"], {"AAA": snapshot(10.7)}, {})
        later = NOW + timedelta(minutes=5)
        state, report = cycle(later, ["AAA"], {"AAA": snapshot(13.1)}, state)
        self.assertEqual(report["new_watch"], [])
        self.assertIsNone(state["tracked"]["AAA"]["max_observed_price_after"])
        state, report = cycle(later, ["AAA"], {"AAA": snapshot(13.1, 5)}, state)
        self.assertEqual(state["tracked"]["AAA"]["milestones"], [15, 20, 30])
        self.assertEqual(state["tracked"]["AAA"]["max_observed_price_after"], 13.1)
        self.assertEqual(report["new_events"][0]["lead_minutes"], 5)

    def test_cap_three_per_cycle_and_no_repeat(self):
        snaps = {s: snapshot(10.8) for s in ("AAA", "BBB", "CCC", "DDD")}
        state, report = cycle(NOW, list(snaps), snaps, {})
        self.assertEqual(len(report["new_watch"]), 3)
        state, report = cycle(NOW + timedelta(minutes=5), list(snaps), snaps, state)
        self.assertEqual(len(report["new_watch"]), 1)

    def test_stale_future_and_missing_trades_not_evidence(self):
        self.assertIsNone(valid_price("AAA", snapshot(10.6, -20), NOW))
        self.assertIsNone(valid_price("AAA", snapshot(10.6, 1), NOW))
        self.assertIsNone(valid_price("AAA", {}, NOW))

    def test_horizon_censors_without_fabricated_high(self):
        state, _ = cycle(NOW, ["AAA"], {"AAA": snapshot(10.7)}, {})
        state, report = cycle(NOW + timedelta(minutes=241), ["AAA"], {}, state)
        self.assertEqual(state["tracked"]["AAA"]["status"], "CENSORED_OR_WINDOW_COMPLETE")
        self.assertIsNone(state["tracked"]["AAA"]["max_observed_price_after"])

    def test_partial_snapshot_coverage_is_explicit(self):
        universe = ["AAA", "BBB", "CCC", "DDD"]
        state, report = cycle(NOW, universe, {"AAA": snapshot(10.6)}, {})
        self.assertEqual(report["universe_size"], 4)
        self.assertEqual(report["valid_fresh_snapshots"], 1)
        self.assertEqual(report["missing_or_stale_snapshots"], 3)
        self.assertEqual(report["coverage_fraction"], 0.25)
        self.assertEqual(len(report["new_watch"]), 1)

    def test_zero_coverage_is_reported_not_a_negative_signal(self):
        _, report = cycle(NOW, ["AAA", "BBB"], {}, {})
        self.assertEqual(report["valid_fresh_snapshots"], 0)
        self.assertEqual(report["missing_or_stale_snapshots"], 2)
        self.assertEqual(report["coverage_fraction"], 0)

    def test_new_york_window(self):
        self.assertTrue(market_window(NOW))
        self.assertFalse(market_window(datetime(2026, 10, 18, 15, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
