import unittest
import tempfile
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from radar.core import analyze, early_band, open_db, record, LABEL
from radar.runner import load_universe, session_window, route_shortlist
from radar.evidence import observed_packet
from radar.bridge import prepare as bridge_prepare, ack as bridge_ack
from radar.health import build as health_build
from radar.semantic_shadow import build as semantic_shadow_build
from radar.shadow_report import build as shadow_report_build

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

    def test_evidence_collector_is_prospective_and_conservative(self):
        db = open_db(':memory:')
        run = db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        record(db, run, 'TEST', self.snapshot(), '2026-10-05T14:00:30Z', '2026-10-05T14:01:00+00:00', 900)
        observation_id = db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
        packet = observed_packet(db, observation_id)
        self.assertEqual(packet['symbol'], 'TEST')
        self.assertEqual(packet['source_ts'], '2026-10-05T14:00:00+00:00')
        self.assertEqual(packet['provenance']['provider'], 'Alpaca')
        self.assertFalse(packet['valid_activity_baseline']['value'])
        self.assertFalse(packet['price_conversion']['value'])
        external = {
            'symbol':'TEST', 'source_ts':'2026-10-05T14:00:00+00:00', 'rvol':3.5,
            'valid_activity_baseline':{'value':True,'provenance':'verified external baseline'}
        }
        merged = observed_packet(db, observation_id, external)
        self.assertEqual(merged['rvol'], 3.5)
        self.assertTrue(merged['valid_activity_baseline']['value'])

    def test_semantic_shadow_records_metrics_without_promoting_frozen_baseline(self):
        db = open_db(':memory:')
        run = db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        snap1 = {'latestTrade': {'p': 10.5, 't': '2026-10-05T14:00:00Z'}, 'prevDailyBar': {'c': 10, 't': '2026-10-02T20:00:00Z'}, 'dailyBar': {'v': 1000}}
        snap2 = {'latestTrade': {'p': 10.8, 't': '2026-10-05T14:05:00Z'}, 'prevDailyBar': {'c': 10, 't': '2026-10-02T20:00:00Z'}, 'dailyBar': {'v': 1500}}
        record(db, run, 'TEST', snap1, '2026-10-05T14:00:00Z', '2026-10-05T14:00:10+00:00', 900)
        first = db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
        semantic_shadow_build(db, first, '2026-10-05T14:00:11+00:00')
        record(db, run, 'TEST', snap2, '2026-10-05T14:05:00Z', '2026-10-05T14:05:10+00:00', 900)
        second = db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
        payload = semantic_shadow_build(db, second, '2026-10-05T14:05:11+00:00')
        self.assertFalse(payload['authoritative'])
        self.assertFalse(payload['frozen_activity_baseline_valid'])
        self.assertTrue(payload['new_observed_high'])
        self.assertAlmostEqual(payload['change_delta_pp'], 3.0, places=6)
        self.assertEqual(db.execute('SELECT count(*) FROM semantic_shadow').fetchone()[0], 2)

    def test_shadow_report_is_non_authoritative(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'radar.sqlite3'
            db = open_db(db_path)
            run = db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
            snap = {'latestTrade': {'p': 10.5, 't': '2026-10-05T14:00:00Z'}, 'prevDailyBar': {'c': 10, 't': '2026-10-02T20:00:00Z'}, 'dailyBar': {'v': 1000}}
            record(db, run, 'TEST', snap, '2026-10-05T14:00:00Z', '2026-10-05T14:00:10+00:00', 900)
            oid = db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
            semantic_shadow_build(db, oid, '2026-10-05T14:00:11+00:00')
            db.commit(); db.close()
            report = shadow_report_build(db_path)
            self.assertFalse(report['authoritative'])
            self.assertEqual(report['status'], 'SHADOW_ONLY')
            self.assertEqual(report['packets'], 1)

    def test_bridge_batches_all_events_and_acks_only_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'radar.sqlite3'
            out_path = Path(directory) / 'signal.json'
            db = open_db(db_path)
            db.execute("INSERT INTO outbox(event_key,created_ts,message) VALUES('signal:1','t1','m1')")
            db.execute("INSERT INTO outbox(event_key,created_ts,message) VALUES('signal:2','t2','m2')")
            db.commit()
            db.close()
            self.assertEqual(bridge_prepare(db_path, out_path), 0)
            payload = json.loads(out_path.read_text())
            self.assertEqual(payload['event_count'], 2)
            self.assertEqual([x['event_key'] for x in payload['events']], ['signal:1','signal:2'])
            db = sqlite3.connect(db_path)
            self.assertEqual(db.execute('SELECT count(*) FROM bridge_publications').fetchone()[0], 0)
            db.close()
            bridge_ack(db_path, out_path, 'abc123')
            db = sqlite3.connect(db_path)
            self.assertEqual(db.execute('SELECT count(*) FROM bridge_publications').fetchone()[0], 2)
            db.close()
            self.assertEqual(bridge_prepare(db_path, out_path), 1)



    def test_discovery_routing_uses_turnover_price_response_and_activity(self):
        snapshots = {
            'TURN': {'latestTrade': {'p': 10}, 'dailyBar': {'v': 1000}},
            'MOVE': {'latestTrade': {'p': 10}, 'dailyBar': {'v': 100}},
            'VOL': {'latestTrade': {'p': 10}, 'dailyBar': {'v': 10000}},
            'OTHER': {'latestTrade': {'p': 10}, 'dailyBar': {'v': 50}},
        }
        caps = {'TURN': 10000, 'MOVE': 1000000, 'VOL': 1000000000, 'OTHER': 1000000}
        changes = {'TURN': 1, 'MOVE': 12, 'VOL': 0.5, 'OTHER': 0}
        selected = route_shortlist(snapshots, caps, changes, 3)
        self.assertEqual(set(selected), {'TURN','MOVE','VOL'})

    def test_health_reports_cycle_and_pending_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'radar.sqlite3'
            db = open_db(db_path)
            run_id = db.execute("INSERT INTO runs(started,finished,status,detail) VALUES(?,?,?,?)",
                ('2026-10-05T14:00:00+00:00','2026-10-05T14:00:10+00:00','MONITOR_OK','one observation')).lastrowid
            record(db, run_id, 'TEST', self.snapshot(), '2026-10-05T14:00:01+00:00', '2026-10-05T14:00:10+00:00', 900)
            db.execute("INSERT INTO outbox(event_key,created_ts,message) VALUES('signal:1','now','m')")
            db.commit()
            db.close()
            payload = health_build(db_path, 0, 0)
            self.assertEqual(payload['latest_run']['status'], 'MONITOR_OK')
            self.assertEqual(payload['observations']['ok'], 1)
            self.assertEqual(payload['pending_bridge_events'], 1)
            self.assertEqual(payload['health'], 'DEGRADED')
            self.assertEqual(payload['model_readiness']['status'], 'BLOCKED_SEMANTIC_EVIDENCE')
            failed = health_build(db_path, 1, 0)
            self.assertEqual(failed['health'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
