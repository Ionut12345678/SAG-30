import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from radar.core import analyze, early_band, open_db, record, LABEL
from radar.runner import load_universe, session_window

class RadarTests(unittest.TestCase):
    def snapshot(self, timestamp='2026-10-05T14:00:00+00:00'):
        return {'latestTrade': {'p': 11, 't': timestamp}, 'prevDailyBar': {'c': 10, 't': '2026-10-02T20:00:00Z'}}

    def test_bands(self):
        for pct, expected in [(4.99,'EXCELLENT'),(5,'IDEAL'),(10,'EARLY VALID'),(15,'SALVAGE'),(20,'LATE'),(None,'UNKNOWN')]:
            self.assertEqual(early_band(pct), expected)

    def test_timestamp_quality(self):
        retrieval = '2026-10-05T14:01:00+00:00'
        self.assertEqual(analyze(self.snapshot(), retrieval, 900)[1], 'OK')
        for stamp in [None, 'bad', '2026-10-05T14:02:00Z', '2026-10-05T13:00:00Z']:
            result = analyze(self.snapshot(stamp), retrieval, 900)
            self.assertEqual(result[1], 'DATA_QUALITY')
            self.assertIsNone(result[4])

    def test_previous_bar_weekend_is_valid(self):
        snapshot = {'latestTrade': {'p': 11, 't': '2026-10-05T14:00:00Z'},
                    'prevDailyBar': {'c': 10, 't': '2026-10-02T20:00:00Z'}}
        result = analyze(snapshot, '2026-10-05T14:01:00+00:00', 900)
        self.assertEqual(result[1], 'OK')

    def test_previous_bar_future_is_rejected(self):
        snapshot = {'latestTrade': {'p': 11, 't': '2026-10-05T14:00:00Z'},
                    'prevDailyBar': {'c': 10, 't': '2026-10-05T14:02:00Z'}}
        result = analyze(snapshot, '2026-10-05T14:01:00+00:00', 900)
        self.assertEqual(result[1], 'DATA_QUALITY')
        self.assertIn('invalid_previous_close_time', result[2])

    def test_prospective_append_and_no_invented_hot(self):
        db = open_db(':memory:')
        run = db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        for _ in range(2):
            record(db, run, 'TEST', self.snapshot(), '2026-10-05T14:00:30Z', '2026-10-05T14:01:00+00:00', 900)
        self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0], 2)
        self.assertEqual(db.execute('SELECT count(*) FROM evaluations WHERE status="UNKNOWN"').fetchone()[0], 2)
        source, retrieved = db.execute('SELECT source_ts,retrieval_ts FROM observations LIMIT 1').fetchone()
        self.assertNotEqual(source, retrieved)
        self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_market_window(self):
        self.assertTrue(session_window(datetime(2026,10,5,14,tzinfo=timezone.utc)))
        self.assertFalse(session_window(datetime(2026,10,4,14,tzinfo=timezone.utc)))

    def test_empty_universe_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.csv'
            path.write_text('symbol,market_cap_usd,as_of\n')
            with self.assertRaises(ValueError):
                load_universe(path)


if __name__ == '__main__':
    unittest.main()
