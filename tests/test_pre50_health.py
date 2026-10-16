import unittest
from radar.pre50_health import classify

OK = {"read_state": "success", "fetch": "success", "resolve": "success", "scan": "success", "persist": "success"}
C = {"requested": 10, "fetched": 10, "missing": {}}
S = {"as_of": "2026-10-15", "candidates": []}


class HealthTests(unittest.TestCase):
    def test_zero_requires_scan(self):
        self.assertEqual(classify(C, OK, S)["candidate_count"], 0)
        self.assertIsNone(classify(C, OK)["candidate_count"])

    def test_failed_resolve_is_gap(self):
        bad = dict(OK, resolve="failure")
        self.assertEqual(classify(C, bad, S)["scanner_status"], "DATA_GAP")

    def test_failed_persist_is_not_published(self):
        self.assertFalse(classify(C, dict(OK, persist="failure"), S)["state_published"])
