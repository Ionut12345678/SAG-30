"""Regression test: v0.4.12 confirmation source errors are counted and never routed."""
import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from radar import v0412_premarket_router as router


class TestV0412ConfirmationFailureAudit(unittest.TestCase):
    def test_confirmation_exception_counts_source_failure(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "radar.sqlite3")
            universe_path = str(Path(td) / "universe.csv")
            with open(universe_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["symbol"])
                writer.writeheader()
                writer.writerow({"symbol": "ABCD"})
            # Thursday, 08 Oct 2026, 08:00 ET
            now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
            class Clock:
                @staticmethod
                def now(tz=None):
                    return now
            board = ('Top Gainers <tr><td class="pf-rank">1</td>'
                     '<td class="pf-sym"><a href="?stock=ABCD">ABCD</a></td>'
                     '<td class="pf-name">Example</td>'
                     '<td class="pf-num">$2.00</td>'
                     '<td class="pf-num pf-pos">5.0%</td>'
                     '<td class="pf-num">1M</td></tr>')
            with patch.object(router, "datetime", Clock), patch.object(router, "fetch", return_value=board), patch.object(router, "chart_latest", side_effect=RuntimeError("chart down")):
                report = router.run(db_path, universe_path)
            self.assertEqual(report["audit"]["source_failures"], 1)
            self.assertEqual(report["audit"]["route_load"], 0)
            self.assertEqual(report["rejected"][0]["reason"], "CONFIRMING_1M_SOURCE_ERROR")
            with sqlite3.connect(db_path) as db:
                status, reason = db.execute("SELECT status,reason FROM v0412_premarket_route").fetchone()
                failures, rejected = db.execute("SELECT source_failures,rejected FROM v0412_cycle_audit").fetchone()
            self.assertEqual(status, "PREMARKET_TRACK_ONLY")
            self.assertEqual(reason, "CONFIRMING_1M_SOURCE_ERROR")
            self.assertEqual((failures, rejected), (1, 1))


if __name__ == "__main__":
    unittest.main()
