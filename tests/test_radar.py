import unittest
import tempfile
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from radar.core import analyze, early_band, open_db, record, LABEL
from radar.runner import load_universe, session_window, route_shortlist, routing_view, routing_momentum
from radar.evidence import observed_packet
from radar.bridge import prepare as bridge_prepare, ack as bridge_ack
from radar.health import build as health_build
from radar.semantic_shadow import build as semantic_shadow_build
from radar.shadow_report import build as shadow_report_build
from radar.volume_baseline_shadow import ingest as baseline_ingest, fields as baseline_fields, historical_range
from radar.candidate_v034 import evaluate as candidate_v034_evaluate
from radar.candidate_v034_report import build as candidate_v034_report_build

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

    def test_intraday_shadow_baseline_is_same_bucket_and_non_authoritative(self):
        db = open_db(':memory:')
        bars = {'TEST': [
            {'t':'2026-10-01T14:00:00Z','v':100},
            {'t':'2026-10-01T14:05:00Z','v':150},
            {'t':'2026-10-02T14:00:00Z','v':200},
            {'t':'2026-10-02T14:05:00Z','v':300},
            {'t':'2026-10-05T14:00:00Z','v':400},
            {'t':'2026-10-05T14:05:00Z','v':600},
        ]}
        baseline_ingest(db, bars)
        fields = baseline_fields(db,'TEST','2026-10-05T14:05:10+00:00')
        self.assertFalse(fields['authoritative'])
        self.assertEqual(fields['shadow_baseline_sample_count'],2)
        self.assertAlmostEqual(fields['shadow_baseline_median_cumulative_volume'],375.0)
        self.assertAlmostEqual(fields['shadow_observed_volume_ratio'],1000.0/375.0)
        override = baseline_fields(db,'TEST','2026-10-05T14:05:10+00:00',750.0)
        self.assertAlmostEqual(override['shadow_observed_volume_ratio'],2.0)

    def test_historical_range_respects_new_york_dst(self):
        winter_start,winter_end=historical_range(datetime(2026,1,15,15,tzinfo=timezone.utc),1)
        summer_start,summer_end=historical_range(datetime(2026,7,15,15,tzinfo=timezone.utc),1)
        self.assertTrue(winter_start.endswith('-05:00'))
        self.assertTrue(winter_end.endswith('-05:00'))
        self.assertTrue(summer_start.endswith('-04:00'))
        self.assertTrue(summer_end.endswith('-04:00'))

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

    def test_v034_candidate_fresh_path_is_prospective_and_never_emits_production_alert(self):
        db = open_db(':memory:')
        run = db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        sequence = [
            ('2026-10-05T14:00:00Z',10.0,0.0,None,None,None,None),
            ('2026-10-05T14:05:00Z',10.3,3.0,10.0,0.0,0.3,3.0),
            ('2026-10-05T14:10:00Z',10.3,3.0,10.3,3.0,0.0,0.0),
            ('2026-10-05T14:15:00Z',10.5,5.0,10.3,3.0,0.2,2.0),
        ]
        states=[]
        for ts,price,pct,prev_price,prev_pct,price_delta,pct_delta in sequence:
            snap={'latestTrade':{'p':price,'t':ts},'prevDailyBar':{'c':10.0,'t':'2026-10-02T20:00:00Z'},'dailyBar':{'v':10000}}
            record(db,run,'TEST',snap,ts,ts.replace('Z','+00:00'),900)
            oid=db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
            payload={
              'symbol':'TEST','retrieval_ts':ts.replace('Z','+00:00'),'source_ts':ts,
              'same_clock_volume_sample_count':5,'observed_same_clock_volume_ratio':4.0,
              'previous_price':prev_price,'previous_change_pct':prev_pct,
              'price_delta':price_delta,'change_delta_pp':pct_delta
            }
            db.execute('CREATE TABLE IF NOT EXISTS semantic_shadow(observation_id INTEGER PRIMARY KEY,recorded_ts TEXT NOT NULL,payload TEXT NOT NULL)')
            db.execute('INSERT INTO semantic_shadow VALUES(?,?,?)',(oid,ts,json.dumps(payload)))
            states.append(candidate_v034_evaluate(db,oid,ts))
        self.assertEqual(states[0],'C34-WATCH')
        self.assertEqual(states[1],'C34-CONVERSION')
        self.assertEqual(states[2],'C34-ACCEPTED')
        self.assertEqual(states[3],'C34-HOT-SHADOW')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM candidate_v034_signals').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],0)

    def test_v034_candidate_requires_five_baseline_sessions(self):
        db = open_db(':memory:')
        run = db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        ts='2026-10-05T14:05:00Z'
        snap={'latestTrade':{'p':10.3,'t':ts},'prevDailyBar':{'c':10.0,'t':'2026-10-02T20:00:00Z'},'dailyBar':{'v':10000}}
        record(db,run,'TEST',snap,ts,ts.replace('Z','+00:00'),900)
        oid=db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
        db.execute('CREATE TABLE semantic_shadow(observation_id INTEGER PRIMARY KEY,recorded_ts TEXT NOT NULL,payload TEXT NOT NULL)')
        db.execute('INSERT INTO semantic_shadow VALUES(?,?,?)',(oid,ts,json.dumps({
          'same_clock_volume_sample_count':4,'observed_same_clock_volume_ratio':100.0,
          'previous_price':10.0,'previous_change_pct':0.0,'price_delta':0.3,'change_delta_pp':3.0
        })))
        state=candidate_v034_evaluate(db,oid,ts)
        self.assertEqual(state,'C34-LOW')

    def test_v034_candidate_report_is_research_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path=Path(directory)/'radar.sqlite3'
            db=open_db(db_path)
            from radar.candidate_v034 import init as candidate_init
            candidate_init(db)
            db.commit(); db.close()
            report=candidate_v034_report_build(db_path)
            self.assertFalse(report['authoritative'])
            self.assertEqual(report['status'],'CANDIDATE_SHADOW_ONLY')

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



    def test_routing_can_use_fresh_minute_bar_without_relaxing_model_quality(self):
        snapshot = {
            'latestTrade': {'p':10.0,'t':'2026-10-05T13:00:00Z'},
            'minuteBar': {'c':10.8,'t':'2026-10-05T14:00:00Z'},
            'prevDailyBar': {'c':10.0,'t':'2026-10-02T20:00:00Z'},
            'dailyBar': {'v':1000},
        }
        route = routing_view(snapshot,'2026-10-05T14:01:00+00:00',900)
        self.assertIsNotNone(route)
        normalized, change, source = route
        self.assertEqual(source,'minuteBar')
        self.assertAlmostEqual(normalized['latestTrade']['p'],10.8)
        self.assertAlmostEqual(change,8.0)

    def test_discovery_routing_can_promote_acceleration_and_fresh_volume_impulse(self):
        snapshots={
            'BASE': {'latestTrade':{'p':10},'dailyBar':{'v':1000}},
            'ACCEL': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
            'IMPULSE': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
            'OTHER': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
        }
        caps={k:1000000 for k in snapshots}
        changes={k:1 for k in snapshots}
        selected=route_shortlist(
            snapshots,caps,changes,2,
            accelerations={'ACCEL':5.0},
            volume_impulses={'IMPULSE':0.25}
        )
        self.assertIn('ACCEL',selected)
        self.assertIn('IMPULSE',selected)

    def test_routing_momentum_is_per_minute_and_same_session(self):
        db=open_db(':memory:')
        run=db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        first={'latestTrade':{'p':10,'t':'2026-10-05T14:00:00Z'},'prevDailyBar':{'c':10,'t':'2026-10-02T20:00:00Z'},'dailyBar':{'v':1000}}
        second={'latestTrade':{'p':10.5,'t':'2026-10-05T14:05:00Z'},'prevDailyBar':{'c':10,'t':'2026-10-02T20:00:00Z'},'dailyBar':{'v':1500}}
        record(db,run,'TEST',first,'2026-10-05T14:00:00Z','2026-10-05T14:00:10+00:00',900)
        record(db,run,'TEST',second,'2026-10-05T14:05:00Z','2026-10-05T14:05:10+00:00',900)
        oid=db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
        accel,impulse=routing_momentum(db,'TEST',oid,5.0,second,1000000,'2026-10-05T14:05:10+00:00')
        self.assertAlmostEqual(accel,1.0,places=6)
        self.assertAlmostEqual(impulse,0.001,places=6)

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
