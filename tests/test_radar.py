import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from radar.core import analyze, early_band, open_db, record, LABEL
from radar.runner import load_universe, session_window, flush_alerts

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
        with self.assertRaises(ValueError):
            load_universe('config/universe.csv')

    @patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN':'test', 'TELEGRAM_CHAT_ID':'test'})
    @patch('radar.runner.request', return_value=({'ok': True}, 'now'))
    def test_alert_delivery(self, request):
        db = open_db(':memory:')
        db.execute('INSERT INTO outbox(event_key,created_ts,message) VALUES(?,?,?)', ('test','now',LABEL))
        flush_alerts(db)
        flush_alerts(db)
        self.assertEqual(request.call_count, 1)
        self.assertIsNotNone(db.execute('SELECT delivered_ts FROM outbox').fetchone()[0])

if __name__ == '__main__':
    unittest.main()
