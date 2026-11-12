"""Regression tests for standalone research vNext, using a synthetic scout cohort."""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from radar.vnext_research import build, rank_candidates


def sample(symbol, pct, accel=1.0, impulse=0.2, turnover=0.1):
    return {"symbol": symbol, "pct": pct, "accel": accel,
            "impulse": impulse, "turnover": turnover}


class VNextTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("""CREATE TABLE scout_history(
            run_id INTEGER, session TEXT, symbol TEXT, retrieval_ts TEXT,
            change_pct REAL, acceleration_pp_per_min REAL,
            fresh_turnover_impulse_per_min REAL, turnover REAL, selected INTEGER)""")
        self.session = "2026-10-08"
        self.t0 = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.db.close()

    def put(self, run, symbol, pct, accel=1, impulse=.2, turnover=.1, offset=0):
        ts = (self.t0 + timedelta(minutes=offset)).isoformat()
        self.db.execute("INSERT INTO scout_history VALUES(?,?,?,?,?,?,?,?,?)",
                        (run, self.session, symbol, ts, pct, accel, impulse, turnover, 1))

    def test_vnext_vs_baseline_at_same_capacity(self):
        self.put(1, "EARLY", 4, offset=0)
        self.put(1, "LATE", 7, accel=0, offset=0)
        self.put(2, "EARLY", 31, offset=10)
        self.put(2, "LATE", 8, accel=0, offset=10)
        result = build(self.db, cap=1, exclude_open_session=False)
        a = result["strategies"]["vnext"]
        b = result["strategies"]["simple"]
        self.assertEqual(a["signals"], 1)
        self.assertEqual(b["signals"], 1)
        self.assertEqual(a["cases"][0]["symbol"], "EARLY")
        self.assertEqual(b["cases"][0]["symbol"], "LATE")
        self.assertEqual(a["hits"]["20"], 1)
        self.assertEqual(b["hits"]["20"], 0)

    def test_censored_not_counted_as_loss(self):
        self.put(1, "NOFOLLOW", 4)
        x = build(self.db, exclude_open_session=False)["strategies"]["vnext"]
        self.assertEqual(x["censored"], 1)
        self.assertIsNone(x["resolved_sampled_hit_rate"]["20"])
        self.assertEqual(x["cases"][0]["hits"], {"15": None, "20": None, "30": None, "50": None})

    def test_partial_horizon_no_hit_is_unknown_not_false_positive(self):
        self.put(1, "PARTIAL", 4, offset=0)
        self.put(2, "PARTIAL", 5, offset=5)
        x = build(self.db, exclude_open_session=False)["strategies"]["vnext"]
        self.assertEqual(x["with_forward_samples"], 1)
        self.assertEqual(x["censored"], 1)
        self.assertEqual(x["resolved_by_threshold"]["20"], 0)
        self.assertIsNone(x["cases"][0]["hits"]["20"])
        self.assertEqual(x["cases"][0]["status"], "CENSORED_PARTIAL_HORIZON")

    def test_full_horizon_negative_is_resolved(self):
        self.put(1, "FULL", 4, offset=0)
        for i in range(1, 25):
            self.put(i + 1, "FULL", 5, offset=i * 10)
        x = build(self.db, exclude_open_session=False)["strategies"]["vnext"]
        self.assertEqual(x["complete_horizon"], 1)
        self.assertEqual(x["resolved_by_threshold"]["20"], 1)
        self.assertFalse(x["cases"][0]["hits"]["20"])

    def test_missing_history_fails_instead_of_reporting_zero(self):
        db = sqlite3.connect(":memory:")
        try:
            with self.assertRaisesRegex(ValueError, "Missing scout_history"):
                build(db)
        finally:
            db.close()

    def test_no_duplicate_alerts_and_no_backdated_first_seen(self):
        self.put(1, "ABC", 3, offset=0)
        self.put(2, "ABC", 6, offset=5)
        self.put(3, "ABC", 32, offset=10)
        x = build(self.db, exclude_open_session=False)["strategies"]["vnext"]
        self.assertEqual(x["signals"], 1)
        self.assertEqual(x["cases"][0]["first_signal_ts"], self.t0.isoformat())

    def test_negative_and_stale_momentum_ineligible(self):
        pool = [sample("A", 4, accel=0), sample("B", 5, impulse=0),
                sample("C", 12), sample("D", 3)]
        self.assertEqual([r["symbol"] for r in rank_candidates(pool, "vnext", 3)], ["D"])

    def test_no_production_or_buy_fields(self):
        self.put(1, "ABC", 2)
        r = build(self.db, exclude_open_session=False)
        self.assertEqual(r["status"], "SHADOW_NOT_BUY")
        self.assertFalse(r["strategies"]["vnext"]["cases"][0]["source_quote_validated"])
        self.assertIsNone(r["strategies"]["vnext"]["cases"][0]["entry_price"])


if __name__ == "__main__":
    unittest.main()
