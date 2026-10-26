"""Run with: python -m unittest discover -s research/radar_v2 -p 'test_*.py'"""
import unittest
from datetime import datetime, timedelta, timezone
from causal_engine import CausalRadar, Quote

T = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)

def q(price, source=T, ingest=T, symbol="XYZ", volume=500):
    return Quote(symbol, "test", source, ingest, price, 100, volume)

class TestCausality(unittest.TestCase):
    def test_discovery_and_later_milestones(self):
        r = CausalRadar()
        self.assertTrue(r.ingest(q(105)).validated)
        self.assertEqual(r.first_seen_by_symbol["XYZ"].first_seen, T)
        r.ingest(q(116, T + timedelta(minutes=1), T + timedelta(minutes=1)))
        self.assertIn(("XYZ", 15), r.milestones)
        self.assertNotIn(("XYZ", 20), r.milestones)

    def test_no_prior_high_backdating(self):
        r = CausalRadar()
        r.ingest(q(130, T - timedelta(minutes=1), T))
        r.ingest(q(105, T, T))
        self.assertEqual(r.milestones, {})

    def test_stale_rejected(self):
        r = CausalRadar()
        self.assertEqual(r.ingest(q(105, T, T + timedelta(minutes=6))).rejection_reason, "stale_quote")
        self.assertEqual(r.first_seen_by_symbol, {})

    def test_duplicates_idempotent(self):
        r = CausalRadar()
        self.assertIsNotNone(r.ingest(q(105)))
        self.assertIsNone(r.ingest(q(105)))
        self.assertEqual(len(r.observations), 1)

    def test_future_source_rejected(self):
        r = CausalRadar()
        self.assertEqual(r.ingest(q(105, T + timedelta(minutes=1), T)).rejection_reason, "future_source_timestamp")

    def test_missing_volume_rejected(self):
        r = CausalRadar()
        self.assertEqual(r.ingest(q(105, volume=None)).rejection_reason, "missing_volume")

    def test_prebreakout_separate(self):
        r = CausalRadar()
        self.assertEqual(r.ingest(q(102)).rejection_reason, "outside_discovery_band")

if __name__ == "__main__":
    unittest.main()
