"""Regression tests for prospective-only evidence persistence."""
import tempfile
import unittest
from pathlib import Path
from prospective_ledger import append_event

BASE={"symbol":"NN","first_seen":"2026-10-26T15:12:00+00:00","provider":"screen",
"source_ts":"2026-10-26T15:11:00+00:00","price":10.1,
"previous_regular_close":9.5,"volume":100,"data_quality":"unverified","kind":"discovery"}

class ProspectiveLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"ledger.jsonl"
    def tearDown(self):
        self.tmp.cleanup()
    def test_duplicate_is_idempotent(self):
        self.assertTrue(append_event(self.path,BASE))
        self.assertFalse(append_event(self.path,BASE))
        self.assertEqual(len(self.path.read_text().splitlines()),1)
    def test_replay_is_rejected(self):
        with self.assertRaises(ValueError):
            append_event(self.path,{**BASE,"mode":"replay"})
    def test_original_discovery_cannot_be_replaced(self):
        append_event(self.path,BASE)
        with self.assertRaises(ValueError):
            append_event(self.path,{**BASE,"first_seen":"2026-10-26T16:00:00+00:00","source_ts":"2026-10-26T15:59:00+00:00"})
    def test_validation_requires_discovery(self):
        with self.assertRaises(ValueError):
            append_event(self.path,{**BASE,"kind":"validated_signal"})
    def test_unverified_cannot_be_validated(self):
        append_event(self.path,BASE)
        with self.assertRaises(ValueError):
            append_event(self.path,{**BASE,"kind":"validated_signal"})
    def test_followup_requires_later_observation(self):
        append_event(self.path,BASE)
        append_event(self.path,{**BASE,"kind":"validated_signal","data_quality":"validated"})
        with self.assertRaises(ValueError):
            append_event(self.path,{**BASE,"kind":"followup","price":12.0})
        self.assertTrue(append_event(self.path,{**BASE,"kind":"followup","first_seen":"2026-10-26T16:12:00+00:00","source_ts":"2026-10-26T16:11:00+00:00","price":12.0}))
if __name__=="__main__":
    unittest.main()
