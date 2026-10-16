"""PRE50 status evidence regression tests."""
import tempfile
import unittest
from pathlib import Path
from radar.pre50_health import classify, write_health

OK = dict(read_state="success", fetch="success", resolve="success", scan="success", persist="success")
COVERAGE = dict(requested=10, fetched=10, missing={})
SCAN = dict(as_of="2026-10-15", candidates=[])

class HealthTests(unittest.TestCase):
    def test_observed_zero_candidates(self):
        r = classify(COVERAGE, OK, SCAN)
        self.assertEqual((r["scanner_status"], r["candidate_count"]), ("OBSERVED", 0))
        self.assertFalse(r["session_complete_verified"])

    def test_skipped_scan_not_zero(self):
        r = classify(COVERAGE, {**OK, "scan": "skipped"}, None)
        self.assertEqual(r["scanner_status"], "DATA_GAP")
        self.assertIsNone(r["candidate_count"])

    def test_resolve_failure(self):
        r = classify(COVERAGE, {**OK, "resolve": "failure"}, SCAN)
        self.assertEqual(r["scanner_status"], "DATA_GAP")

    def test_partial_and_fetch_failure(self):
        c = dict(requested=10, fetched=8, missing={"X": "timeout"})
        self.assertEqual(classify(c, OK, SCAN)["scanner_status"], "PARTIAL_OBSERVED")
        self.assertEqual(classify(c, {**OK, "fetch": "failure"}, SCAN)["scanner_status"], "DATA_GAP")

    def test_persist_failure(self):
        r = classify(COVERAGE, {**OK, "persist": "failure"}, SCAN)
        self.assertEqual(r["scanner_status"], "OBSERVED")
        self.assertFalse(r["state_published"])

    def test_missing_files_still_write_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = write_health(tmp, {**OK, "scan": "skipped"})
            self.assertEqual(r["scanner_status"], "DATA_GAP")
            self.assertTrue((Path(tmp) / "health.json").exists())

if __name__ == "__main__":
    unittest.main()
