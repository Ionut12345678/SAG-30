"""State integrity regression tests."""
import tempfile
import unittest
from pathlib import Path
from state_integrity import check,seal

class StateIntegrityTests(unittest.TestCase):
    def test_missing_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(check(Path(d)/"ledger",Path(d)/"manifest")["reason"],"NO_PREVIOUS_STATE")
    def test_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"ledger";m=Path(d)/"manifest"
            p.write_text('{"mode":"prospective","first_seen":"2026-10-26T10:00:00Z","source_ts":"2026-10-26T09:59:00Z"}\n')
            seal(p,m)
            self.assertTrue(check(p,m)["ok"])
            p.write_text(p.read_text()+"\n")
            self.assertEqual(check(p,m)["reason"],"STATE_HASH_MISMATCH")
    def test_replay_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"ledger";m=Path(d)/"manifest"
            p.write_text('{"mode":"replay","first_seen":"2026-10-26T10:00:00Z","source_ts":"2026-10-26T09:59:00Z"}\n')
            seal(p,m)
            self.assertEqual(check(p,m)["reason"],"NON_PROSPECTIVE_EVENT")
