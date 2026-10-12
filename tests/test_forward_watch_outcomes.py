import unittest
from datetime import datetime, timezone
from radar.forward_watch_outcomes import build

T = datetime(2026, 10, 12, 22, tzinfo=timezone.utc)
W = {"session":"2026-10-12","symbol":"TEST","ts":"2026-10-12T17:00:00Z","change_pct":5}
def row(ts,p): return {"session":"2026-10-12","symbol":"TEST","ts":ts,"change_pct":p}

class ForwardWatchTests(unittest.TestCase):
    def test_later_30_and_50(self):
        r = build([W],[row("2026-10-12T17:05:00Z",31),row("2026-10-12T17:10:00Z",52)],T)
        self.assertEqual(r["verified_post_watch_30"],1)
        self.assertEqual(r["verified_post_watch_50"],1)
        self.assertAlmostEqual(r["cases"][0]["max_pct_return_from_watch_reference"],44.7619,places=3)

    def test_same_timestamp_not_future(self):
        r = build([W],[row(W["ts"],99)],T)
        self.assertEqual(r["verified_post_watch_50"],0)
        self.assertEqual(r["cases"][0]["status"],"NO_LATER_OBSERVATION")

    def test_already_above_target_gets_no_credit(self):
        w = dict(W,change_pct=35)
        r = build([w],[row("2026-10-12T17:10:00Z",40)],T)
        self.assertFalse(r["cases"][0]["milestones"]["30"]["qualifies_post_watch"])

    def test_future_data_excluded(self):
        r = build([W],[row("2026-10-13T17:05:00Z",80)],T)
        self.assertEqual(r["cases"][0]["future_observation_count"],0)

    def test_older_and_duplicate_rows(self):
        r = build([W,W],[row("2026-10-12T16:00:00Z",90),
                          row("2026-10-12T17:05:00Z",8),
                          row("2026-10-12T17:05:00Z",70)],T)
        self.assertEqual(r["watch_count"],1)
        self.assertEqual(r["cases"][0]["future_observation_count"],1)
        self.assertEqual(r["verified_post_watch_50"],0)

    def test_invalid_values_ignored(self):
        r = build([W],[row("2026-10-12T17:05:00Z","nan")],T)
        self.assertEqual(r["with_later_observation"],0)

if __name__=="__main__":
    unittest.main()
