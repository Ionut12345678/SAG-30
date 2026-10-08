"""Regression tests for SCOUT rank capture and collector semantics."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from radar_rank_capture_hook import record_cycle
from collect_scout_snapshots import collect

TS="2026-10-08T15:00:00+00:00"

class CollectorTests(unittest.TestCase):
    def test_ranks_at_cycle(self):
        rows=record_cycle([{"symbol":"AAA","rank":5,"selected":False},
                           {"symbol":"BBB","rank":90,"selected":True}],TS)
        self.assertEqual([r["rank"] for r in rows],[5,90])
        self.assertEqual(rows[0]["selected"],False)

    def test_duplicate_symbol_rejected(self):
        with self.assertRaises(ValueError):
            record_cycle([{"symbol":"AAA","rank":1},{"symbol":"AAA","rank":2}],TS)

    def test_invalid_rank_rejected(self):
        with self.assertRaises(ValueError):
            record_cycle([{"symbol":"AAA","rank":True}],TS)

    def test_deep_is_not_shortlist(self):
        rows=collect({"scout_to_deep":[{"symbol":"AAA","scout_ts":TS,
                                        "deep_retrieval_ts":TS}]})
        self.assertFalse(rows[0]["selected"])
        self.assertTrue(rows[0]["deep_routed"])
        self.assertIsNone(rows[0]["rank"])

    def test_snapshot_rank_is_observed(self):
        snapshot=record_cycle([{"symbol":"AAA","rank":40,"selected":True}],TS)
        rows=collect({"scout_rank_snapshots":snapshot})
        self.assertEqual(rows[0]["rank"],40)
        self.assertEqual(rows[0]["rank_quality"],"OBSERVED")

if __name__=="__main__":unittest.main()
