"""Regression tests for SCOUT rank capture and collector semantics."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from radar_rank_capture_hook import record_cycle, append_cycle
import tempfile
import json
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

    def test_atomic_ledger_deduplicates_cycles(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"scout.jsonl"
            candidates=[{"symbol":"AAA","rank":4},{"symbol":"BBB","rank":8}]
            first=append_cycle(path,candidates,TS)
            second=append_cycle(path,candidates,TS)
            lines=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(first["new_rows"],2)
            self.assertEqual(second["new_rows"],0)
            self.assertEqual(len(lines),2)

    def test_snapshot_rank_is_observed(self):
        snapshot=record_cycle([{"symbol":"AAA","rank":40,"selected":True}],TS)
        rows=collect({"scout_rank_snapshots":snapshot})
        self.assertEqual(rows[0]["rank"],40)
        self.assertEqual(rows[0]["rank_quality"],"OBSERVED")

if __name__=="__main__":unittest.main()
