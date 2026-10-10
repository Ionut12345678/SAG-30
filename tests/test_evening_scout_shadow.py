import sqlite3
import unittest

from radar.evening_scout_shadow import ingest, handoff


class EveningScoutTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def test_immutable_first_observation_and_handoff(self):
        a = dict(symbol="TEST", price=4.0, retrieval_ts_utc="2026-10-09T21:05:00Z",
                 source="prospective-feed", coverage={"eligible": True})
        self.assertTrue(ingest(self.db, **a))
        self.assertFalse(ingest(self.db, **{**a, "price": 9.0,
                                          "retrieval_ts_utc": "2026-10-09T21:10:00Z"}))
        rows = handoff(self.db, origin_session_et="2026-10-09")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["first_price"], 4.0)

    def test_outside_evening_does_not_enter(self):
        self.assertFalse(ingest(self.db, symbol="TEST", price=4,
            retrieval_ts_utc="2026-10-09T14:00:00Z", source="feed"))
        self.assertEqual(handoff(self.db, origin_session_et="2026-10-09"), [])

    def test_future_source_rejected(self):
        with self.assertRaises(ValueError):
            ingest(self.db, symbol="TEST", price=4,
                retrieval_ts_utc="2026-10-09T21:00:00Z",
                source_ts_utc="2026-10-09T21:01:00Z", source="feed")


if __name__ == "__main__":
    unittest.main()
