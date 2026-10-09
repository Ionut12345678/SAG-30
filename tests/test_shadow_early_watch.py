import unittest
from radar.shadow_early_watch import screen

class EarlyWatchTest(unittest.TestCase):
    def test_broad_early_price_trigger(self):
        rows=[{"ts":"2026-10-09T14:00:00Z","change_pct":1},
              {"ts":"2026-10-09T14:05:00Z","change_pct":3.1},
              {"ts":"2026-10-09T14:20:00Z","change_pct":45}]
        r=screen(rows)
        self.assertEqual(r["first_watch_ts"],"2026-10-09T14:05:00+00:00")
        self.assertIn("PRICE_3",r["trigger_lanes"])
    def test_no_future_leakage(self):
        earlier=[{"ts":"2026-10-09T14:00:00Z","change_pct":0}]
        self.assertEqual(screen(earlier)["status"],"NO_WATCH")
        self.assertEqual(screen(earlier+[{"ts":"2026-10-09T14:20:00Z","change_pct":50}])["first_watch_ts"],"2026-10-09T14:20:00+00:00")
    def test_momentum_can_watch_below_three(self):
        r=screen([{"ts":"2026-10-09T14:00:00Z","change_pct":0},
                  {"ts":"2026-10-09T14:04:00Z","change_pct":2.5}])
        self.assertIn("MOMENTUM_5M_2",r["trigger_lanes"])
    def test_no_data(self):
        self.assertEqual(screen([])["status"],"NO_WATCH")
if __name__=="__main__":
    unittest.main()
