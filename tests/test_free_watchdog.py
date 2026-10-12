import unittest
from datetime import datetime, timedelta, timezone
from radar.free_watchdog import evaluate


NOW = datetime(2026, 10, 12, 18, 30, tzinfo=timezone.utc)


def good():
    return {"generated_ts": NOW.isoformat(), "health": "PASS",
            "checkpoint": {"part_count": 2, "size_status": "OK"},
            "cadence": {"status": "PASS"},
            "fast_scout": {"status": "PASS"}}


class FreeWatchdogTests(unittest.TestCase):
    def test_fresh_healthy_snapshot(self):
        self.assertEqual(evaluate(good(), NOW)["status"], "PASS")

    def test_stale_snapshot_not_live(self):
        value = good()
        value["generated_ts"] = (NOW - timedelta(minutes=40)).isoformat()
        self.assertIn("STALE_HEARTBEAT", evaluate(value, NOW)["reasons"])

    def test_future_timestamp(self):
        value = good()
        value["generated_ts"] = (NOW + timedelta(minutes=10)).isoformat()
        self.assertIn("FUTURE_HEARTBEAT", evaluate(value, NOW)["reasons"])

    def test_missing_timestamp(self):
        value = good()
        value.pop("generated_ts")
        self.assertIn("MISSING_HEARTBEAT_TIMESTAMP", evaluate(value, NOW)["reasons"])

    def test_degraded_and_cadence(self):
        value = good()
        value["health"] = "DEGRADED"
        value["cadence"]["status"] = "MISSED_TARGET"
        reasons = evaluate(value, NOW)["reasons"]
        self.assertIn("NON_HEALTHY_REPORTED", reasons)
        self.assertIn("CADENCE_MISSED_TARGET", reasons)

    def test_storage_warning_and_missing_parts(self):
        value = good()
        value["checkpoint"] = {"part_count": 0, "size_status": "CRITICAL_90_MIB"}
        reasons = evaluate(value, NOW)["reasons"]
        self.assertIn("CHECKPOINT_PARTS_UNKNOWN", reasons)
        self.assertIn("CHECKPOINT_SIZE_WARNING", reasons)

    def test_no_mutation_of_input(self):
        value = good()
        prior = repr(value)
        evaluate(value, NOW)
        self.assertEqual(repr(value), prior)


if __name__ == "__main__":
    unittest.main()
