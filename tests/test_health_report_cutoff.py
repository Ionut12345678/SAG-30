"""Premarket audit counts must stop at the report's injected clock."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from radar.health import build


class HealthReportCutoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'audit.sqlite'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE runs(id INTEGER, started TEXT, finished TEXT, status TEXT, detail TEXT);
            CREATE TABLE observations(id INTEGER, run_id INTEGER, symbol TEXT, retrieval_ts TEXT,
                source_ts TEXT, quality TEXT, reason TEXT, payload TEXT);
            CREATE TABLE evaluations(observation_id INTEGER, status TEXT);
            CREATE TABLE candidates(symbol TEXT);
            CREATE TABLE outbox(event_key TEXT);
            CREATE TABLE v0412_premarket_route(symbol TEXT, session TEXT, status TEXT, observed_ts TEXT);
            INSERT INTO runs VALUES(1, '2026-10-12T12:00:00+00:00',
                '2026-10-12T12:04:00+00:00', 'SUCCESS', 'fixture');
            INSERT INTO v0412_premarket_route VALUES('ABC', '2026-10-12',
                'EARLY_PREMARKET_ROUTE_SHADOW', '2026-10-12T12:00:00+00:00');
        """)
        self.now = datetime(2026, 10, 12, 12, 2, tzinfo=timezone.utc)

    def observe(self, timestamp):
        self.db.execute('INSERT INTO observations VALUES(1,1,?,?,?,?,?,?)',
                        ('ABC', timestamp, timestamp, 'OK', '', '{}'))
        self.db.commit()

    def report(self):
        self.db.commit()
        with patch('radar.freshness.quote_diagnostic',
                   return_value={'reason': None, 'status': 'UNKNOWN'}):
            return build(self.path, now=self.now)

    def test_future_conversion_observation_is_excluded(self):
        self.observe('2026-10-12T12:03:00+00:00')
        result = self.report()['v0412_session_iex_conversion']
        for key in ('observed_after_route', 'valid_after_route',
                    'valid_after_08_et', 'valid_source_after_08_et'):
            self.assertEqual(result[key], 0, key)
        self.assertEqual(result['converted_symbols'], [])

    def test_observation_at_cutoff_is_included(self):
        self.observe(self.now.isoformat())
        result = self.report()['v0412_session_iex_conversion']
        self.assertEqual(result['valid_source_after_08_et'], 1)
        self.assertEqual(result['converted_symbols'], ['ABC'])

    def test_same_run_route_after_report_is_excluded(self):
        self.db.execute("UPDATE v0412_premarket_route SET observed_ts='2026-10-12T12:03:00+00:00'")
        self.assertEqual(self.report()['v0412_downstream']['same_run_routes'], 0)

    def test_same_run_route_after_finished_run_is_excluded(self):
        self.db.execute("UPDATE runs SET finished='2026-10-12T12:01:00+00:00'")
        self.db.execute("UPDATE v0412_premarket_route SET observed_ts='2026-10-12T12:01:30+00:00'")
        self.assertEqual(self.report()['v0412_downstream']['same_run_routes'], 0)

    def test_unfinished_run_still_uses_report_cutoff(self):
        self.db.execute('UPDATE runs SET finished=NULL')
        self.db.execute("UPDATE v0412_premarket_route SET observed_ts='2026-10-12T12:03:00+00:00'")
        self.assertEqual(self.report()['v0412_downstream']['same_run_routes'], 0)


if __name__ == '__main__':
    unittest.main()
