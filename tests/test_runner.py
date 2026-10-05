import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from radar.runner import run, flush_alerts
from radar.core import open_db, LABEL

class RunnerTests(unittest.TestCase):
    @patch.dict(os.environ,{'ALPACA_API_KEY':'synthetic','ALPACA_SECRET_KEY':'synthetic'})
    def test_end_to_end_mocked_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = root/'universe.csv'
            universe.write_text('symbol,market_cap_usd,as_of\nTEST,100000000,2026-10-05\n')
            config = root/'config.json'
            config.write_text(json.dumps({'feed':'iex','universe_file':str(universe),'discovery_interval_seconds':900,'shortlist_limit':30,'max_source_age_seconds':900}))
            timestamp = '2026-10-05T14:00:00+00:00'
            snapshot = {'TEST':{'latestTrade':{'p':10.5,'t':timestamp},'prevDailyBar':{'c':10,'t':'2026-10-02T20:00:00Z'},'dailyBar':{'v':1000}}}
            with patch.dict(os.environ,{'RADAR_CONFIG':str(config),'RADAR_DB':str(root/'state.db')}), patch('radar.runner.utcnow',return_value=timestamp), patch('radar.runner.time.sleep'), patch('radar.runner.request',side_effect=[([{'date':'2026-10-05'}],timestamp),(snapshot,timestamp)]):
                run()
            db = open_db(root/'state.db')
            self.assertEqual(db.execute('SELECT status FROM runs').fetchone()[0],'DISCOVERY_OK')
            self.assertEqual(db.execute('SELECT symbol FROM candidates').fetchone()[0],'TEST')
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM signals').fetchone()[0],0)

    @patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'})
    @patch('radar.runner.request',side_effect=RuntimeError('synthetic failure'))
    def test_alert_failure_retained(self, request):
        db = open_db(':memory:')
        db.execute('INSERT INTO outbox(event_key,created_ts,message) VALUES(?,?,?)',('test','now',LABEL))
        flush_alerts(db)
        delivered, attempts = db.execute('SELECT delivered_ts,attempts FROM outbox').fetchone()
        self.assertIsNone(delivered)
        self.assertEqual(attempts,1)
