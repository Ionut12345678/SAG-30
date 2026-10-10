"""Regression guard: evening integration must remain additive and research-only."""
from pathlib import Path
import unittest

from radar import runner


class EveningWiringTests(unittest.TestCase):
    def test_runner_exposes_shadow_handoff(self):
        self.assertTrue(callable(runner.ingest_evening_scout))
        self.assertTrue(callable(runner.evening_handoff))

    def test_no_frozen_model_changes_in_integration(self):
        source = Path(runner.__file__).read_text()
        self.assertIn("SAG30_EVENING_FOLLOW", source)
        self.assertIn("SAG30_EVENING_SCOUT_REJECT", source)
        self.assertIn("DATA_GAP_MISSING_SNAPSHOT", source)
        self.assertLess(source.index("follow_evening_shadow(db,run_id,now,universe,headers,config,trading_sessions=calendar)"), source.index("if broad:"))
        self.assertIn("local_hour >= 16", source)

if __name__ == "__main__":
    unittest.main()
