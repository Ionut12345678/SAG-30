import csv
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from radar.pre50_fetch import fetch
from radar.pre50 import main

NOW = datetime(2026, 10, 15, 16, 48, tzinfo=timezone.utc)


def history(end='2026-10-15'):
    dates = pd.date_range(end=end, periods=50, tz='America/New_York')
    return pd.DataFrame({'Open': 10., 'High': 11., 'Low': 9., 'Close': 10., 'Volume': 100000}, index=dates)


class DailyFetchTests(unittest.TestCase):
    def test_incomplete_day_removed_before_writing(self):
        feed = types.SimpleNamespace(Ticker=lambda _: types.SimpleNamespace(history=lambda **_: history()))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, yfinance=feed):
            report = fetch(['AAA'], tmp, now=NOW)
            self.assertEqual(report['fetched'], 1)
            self.assertEqual(report['expected_session'], '2026-10-14')
            with (Path(tmp) / 'AAA.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[-1]['date'], '2026-10-14')
            self.assertEqual(len(rows), 49)

    def test_stale_history_fails_and_removes_prior_file(self):
        feed = types.SimpleNamespace(Ticker=lambda _: types.SimpleNamespace(history=lambda **_: history('2026-10-13')))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, yfinance=feed):
            (Path(tmp) / 'AAA.csv').write_text('obsolete')
            report = fetch(['AAA'], tmp, now=NOW)
            self.assertEqual(report['fetched'], 0)
            self.assertIn('AAA', report['missing'])
            self.assertFalse((Path(tmp) / 'AAA.csv').exists())

    def test_live_resolve_cannot_resolve_from_open_session_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            frame = history()
            frame.index.name = 'date'
            frame.columns = [c.lower() for c in frame.columns]
            frame.index = frame.index.strftime('%Y-%m-%d')
            frame.to_csv(folder / 'AAA.csv')
            (folder / 'tickers').write_text('AAA\n')
            event = {'symbol': 'AAA', 'date': '2026-10-14', 'close': 10, 'resolved': None}
            (folder / 'journal').write_text(json.dumps([event]))
            argv = ['pre50', 'resolve', '--live-session', '--data-dir', tmp,
                    '--tickers', str(folder / 'tickers'), '--journal', str(folder / 'journal'),
                    '--output', str(folder / 'report')]
            with patch.object(sys, 'argv', argv), patch('radar.pre50_sessions.latest_completed_session', return_value='2026-10-14'):
                main()
            self.assertIsNone(json.loads((folder / 'journal').read_text())[0]['resolved'])
