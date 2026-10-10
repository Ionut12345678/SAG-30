"""Independent evening carry does not require intraday ranking."""
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from radar import runner
from radar.evening_scout_shadow import ingest


class EveningFollowTests(unittest.TestCase):
    def test_friday_to_monday_without_intraday_features(self):
        db=sqlite3.connect(":memory:")
        ingest(db,symbol="TEST",price=3.0,
               retrieval_ts_utc="2026-10-09T20:30:00+00:00",
               source="iex:latestTrade",source_ts_utc="2026-10-09T20:29:00+00:00")
        def fake_batches(symbols,headers,feed,workers):
            self.assertEqual(symbols,["TEST"])
            yield 0, symbols, "2026-10-12T12:00:00+00:00", {}, "2026-10-12T12:00:00+00:00"
        with patch.object(runner,"fetch_snapshot_batches",side_effect=fake_batches):
            count=runner.follow_evening_shadow(
                db,1,datetime(2026,10,12,12,tzinfo=timezone.utc),
                ["TEST"],{},{"feed":"iex","max_source_age_seconds":900})
        self.assertEqual(count,1)
        row=db.execute("SELECT origin_session_et,status FROM evening_follow_shadow").fetchone()
        self.assertEqual(row,("2026-10-09","DATA_GAP_NO_FRESH_QUOTE"))
        self.assertEqual(db.execute("SELECT first_price FROM evening_scout_shadow").fetchone()[0],3.0)


if __name__=="__main__":
    unittest.main()
