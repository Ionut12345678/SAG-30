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
from radar.candidate_v034r2 import evaluate as candidate_v034r2_evaluate
from radar.candidate_v034_report import build as candidate_v034_report_build
from radar.multi_engine_shadow import evaluate as multi_engine_evaluate, record as multi_engine_record, init as multi_engine_init
from radar.scout import init as scout_init
from radar.winner_recall_report import build as winner_recall_build

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

    def test_v034r2_keeps_activity_memory_when_rvol_falls(self):
        db=open_db(':memory:')
        run=db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        sequence=[
          ('2026-10-05T14:00:00Z',10.0,0.0,4.0,10.0,-0.5),
          ('2026-10-05T14:05:00Z',10.3,3.0,2.0,10.0,0.0),
          ('2026-10-05T14:10:00Z',10.3,3.0,2.0,10.3,3.0),
          ('2026-10-05T14:15:00Z',10.5,5.0,2.0,10.3,3.0),
        ]
        states=[]
        previous_price=None; previous_pct=None
        for ts,price,pct,rvol,_,_ in sequence:
            snap={'latestTrade':{'p':price,'t':ts},'prevDailyBar':{'c':10.0,'t':'2026-10-02T20:00:00Z'},'dailyBar':{'v':10000}}
            record(db,run,'TEST',snap,ts,ts.replace('Z','+00:00'),900)
            oid=db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
            db.execute('CREATE TABLE IF NOT EXISTS semantic_shadow(observation_id INTEGER PRIMARY KEY,recorded_ts TEXT NOT NULL,payload TEXT NOT NULL)')
            db.execute('INSERT INTO semantic_shadow VALUES(?,?,?)',(oid,ts,json.dumps({
              'same_clock_volume_sample_count':5,'observed_same_clock_volume_ratio':rvol,
              'previous_price':previous_price,'previous_change_pct':previous_pct,
              'price_delta':None if previous_price is None else price-previous_price,
              'change_delta_pp':None if previous_pct is None else pct-previous_pct
            })))
            states.append(candidate_v034r2_evaluate(db,oid,ts))
            previous_price=price; previous_pct=pct
        self.assertEqual(states[0],'C34R2-WATCH')
        self.assertEqual(states[1],'C34R2-CONVERSION')
        self.assertEqual(states[2],'C34R2-ACCEPTED')
        self.assertEqual(states[3],'C34R2-HOT-SHADOW')

    def test_v034r2_blocks_negative_context_conversion(self):
        db=open_db(':memory:')
        run=db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
        seq=[
          ('2026-10-05T14:00:00Z',9.0,-10.0,4.0,None,None),
          ('2026-10-05T14:05:00Z',9.2,-8.0,2.0,9.0,-10.0),
        ]
        states=[]
        for ts,price,pct,rvol,pp,pc in seq:
            snap={'latestTrade':{'p':price,'t':ts},'prevDailyBar':{'c':10.0,'t':'2026-10-02T20:00:00Z'},'dailyBar':{'v':10000}}
            record(db,run,'TEST',snap,ts,ts.replace('Z','+00:00'),900)
            oid=db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
            db.execute('CREATE TABLE IF NOT EXISTS semantic_shadow(observation_id INTEGER PRIMARY KEY,recorded_ts TEXT NOT NULL,payload TEXT NOT NULL)')
            db.execute('INSERT INTO semantic_shadow VALUES(?,?,?)',(oid,ts,json.dumps({
              'same_clock_volume_sample_count':5,'observed_same_clock_volume_ratio':rvol,
              'previous_price':pp,'previous_change_pct':pc,
              'price_delta':None if pp is None else price-pp,
              'change_delta_pp':None if pc is None else pct-pc
            })))
            states.append(candidate_v034r2_evaluate(db,oid,ts))
        self.assertEqual(states[0],'C34R2-WATCH')
        self.assertEqual(states[1],'C34R2-WATCH')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM candidate_v034r2_signals').fetchone()[0],0)

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
            'TURN': {'latestTrade':{'p':10},'dailyBar':{'v':10000}},
            'MOVE': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
            'ACCEL': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
            'IMPULSE': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
            'OTHER1': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
            'OTHER2': {'latestTrade':{'p':10},'dailyBar':{'v':100}},
        }
        caps={k:1000000 for k in snapshots}
        changes={k:1 for k in snapshots}; changes['MOVE']=12
        selected=route_shortlist(
            snapshots,caps,changes,4,
            accelerations={'ACCEL':5.0},
            volume_impulses={'IMPULSE':0.25}
        )
        self.assertEqual(set(selected),{'TURN','MOVE','ACCEL','IMPULSE'})

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
        self.assertAlmostEqual(impulse,0.00105,places=6)

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

    def test_winner_recall_audit_distinguishes_shortlist_and_model_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path=Path(directory)/'radar.sqlite3'
            db=open_db(db_path); scout_init(db)
            db.execute("CREATE TABLE candidate_v034r2_events(observation_id INTEGER PRIMARY KEY,evaluated_ts TEXT,symbol TEXT,session TEXT,state TEXT,lane TEXT,change_pct REAL,rvol REAL,baseline_samples INTEGER,detail TEXT,spec_sha256 TEXT)")
            # A is visible early but never selected -> SHORTLIST_MISS.
            # B is selected early and gets a valid deep WATCH but never HOT -> MODEL_MISS.
            rows=[
              (1,'2026-10-05','A','2026-10-05T14:00:00+00:00',5.0,1,1,1,1,0,0),
              (2,'2026-10-05','A','2026-10-05T14:05:00+00:00',35.0,1,1,1,1,0,0),
              (1,'2026-10-05','B','2026-10-05T14:00:00+00:00',6.0,1,1,1,1,1,0),
              (2,'2026-10-05','B','2026-10-05T14:05:00+00:00',40.0,1,1,1,1,1,0),
            ]
            for run_id,session,symbol,ts,pct,rc,ra,ri,rt,sel,sticky in rows:
                db.execute("INSERT INTO scout_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id,session,symbol,ts,pct,1.0,1.0,1.0,'latestTrade',rc,ra,ri,rt,sel,sticky))
            run=db.execute("INSERT INTO runs(started,status) VALUES('2026-10-05T14:00:00+00:00','DISCOVERY_OK')").lastrowid
            snap={'latestTrade':{'p':10.6,'t':'2026-10-05T14:00:00Z'},'prevDailyBar':{'c':10.0,'t':'2026-10-02T20:00:00Z'}}
            record(db,run,'B',snap,'2026-10-05T14:00:00Z','2026-10-05T14:00:01+00:00',900)
            oid=db.execute('SELECT MAX(id) FROM observations').fetchone()[0]
            db.execute("INSERT INTO candidate_v034r2_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (oid,'2026-10-05T14:00:02+00:00','B','2026-10-05','C34R2-WATCH','FRESH',6.0,4.0,5,'watch','x'))
            db.commit(); db.close()
            report=winner_recall_build(db_path)
            by_symbol={x['symbol']:x for x in report['winners']}
            self.assertEqual(by_symbol['A']['classification_under_10'],'SHORTLIST_MISS')
            self.assertEqual(by_symbol['B']['classification_under_10'],'MODEL_MISS')
            self.assertEqual(report['winner_sessions'],2)

    def test_deep_timing_miss_is_not_mislabeled_baseline(self):
        from radar.winner_recall_report import _classify
        from unittest.mock import patch
        rows=[
            {'retrieval_ts':'2026-10-05T14:00:00+00:00','change_pct':3.0,'selected':1},
            {'retrieval_ts':'2026-10-05T14:10:00+00:00','change_pct':32.0,'selected':1},
        ]
        late=[{'retrieval_ts':'2026-10-05T14:05:00+00:00',
               'change_pct':15.0,'baseline_samples':1,'state':'C34R2-LOW'}]
        with patch('radar.winner_recall_report._deep_r2',return_value=late):
            cls,_,_,_=_classify(None,'TEST','2026-10-05',rows,rows[1],10)
        self.assertEqual(cls,'DEEP_TIMING_MISS')
        early=[dict(late[0],change_pct=6.0)]
        with patch('radar.winner_recall_report._deep_r2',return_value=early):
            cls,_,_,_=_classify(None,'TEST','2026-10-05',rows,rows[1],10)
        self.assertEqual(cls,'BASELINE_MISS')

    def test_baseline_miss_diagnostic_is_pre_target_and_research_only(self):
        from radar.winner_recall_report import _baseline_diagnostic
        rows = [
            {'retrieval_ts':'2026-10-08T13:00:00+00:00','change_pct':1.0,'selected':1},
            {'retrieval_ts':'2026-10-08T13:20:00+00:00','change_pct':35.0,'selected':1},
        ]
        deep = [
            {'retrieval_ts':'2026-10-08T13:05:00+00:00','change_pct':3.0,
             'baseline_samples':2,'state':'C34R2-LOW'},
            {'retrieval_ts':'2026-10-08T13:25:00+00:00','change_pct':45.0,
             'baseline_samples':8,'state':'C34R2-HOT-SHADOW'},
        ]
        d = _baseline_diagnostic(rows, deep, '2026-10-08T13:20:00+00:00')
        self.assertEqual(d['reason'], 'INSUFFICIENT_EARLY_BASELINE')
        self.assertEqual(d['max_early_baseline_samples'], 2)
        self.assertEqual(d['early_deep_observations'], 1)
        self.assertEqual(d['status'], 'DIAGNOSTIC_SHADOW_NOT_BUY')
        self.assertIsNone(_baseline_diagnostic(
            [{'retrieval_ts':'2026-10-08T13:00:00+00:00',
              'change_pct':12.0,'selected':1}], deep,
            '2026-10-08T13:20:00+00:00'))

    def test_prospective_retention_outcomes_and_semantic_blockers(self):
        from radar.research_audit import retention_outcomes, semantic_blockers
        from radar.retention_shadow import init as retention_init
        with tempfile.TemporaryDirectory() as td:
            db=open_db(Path(td)/'audit.sqlite')
            scout_init(db)
            retention_init(db)
            db.execute("CREATE TABLE evidence(observation_id INTEGER PRIMARY KEY,payload TEXT)")
            db.execute("CREATE TABLE semantic_shadow(observation_id INTEGER PRIMARY KEY,payload TEXT)")
            # Past closed session: one winner and one loser. Never use pre-entry +30.
            for symbol in ('WIN','LOSS'):
                db.execute("INSERT INTO retention_shadow_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (3,'2026-10-05',symbol,'2026-10-05T14:00:00+00:00',5,
                     '2026-10-05T14:05:00+00:00','2026-10-05T14:04:59+00:00',1,
                     2.0,'iex','SHADOW_FRESH_TRADE'))
                for run,ts,pct in ((2,'2026-10-05T14:00:00+00:00',5),
                                   (4,'2026-10-05T14:10:00+00:00',35 if symbol=='WIN' else 6)):
                    db.execute("INSERT INTO scout_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (run,'2026-10-05',symbol,ts,pct,0,0,0,'latestTrade',1,1,1,1,0,0))
            # No production observations: challenger first by construction.
            out=retention_outcomes(db,datetime.fromisoformat('2026-10-08T16:00:00+00:00'))
            self.assertEqual((out['finalized'],out['observed_30_after'],out['early_and_30']),(2,1,1))
            self.assertEqual(out['observed_30_rate'],0.5)
            db.execute("INSERT INTO runs(id,started,status) VALUES(1,'2026-10-05T14:00:00+00:00','DISCOVERY_OK')")
            db.execute("INSERT INTO observations(run_id,symbol,retrieval_ts,source_ts,request_started_ts,quality,reason,price,change_pct,band,payload,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (1,'WIN','2026-10-05T14:00:00+00:00','2026-10-05T13:59:59+00:00',
                 '2026-10-05T13:59:58+00:00','OK','',2,5,'IDEAL','{}','hash'))
            oid=db.execute("SELECT id FROM observations").fetchone()[0]
            db.execute("INSERT INTO evidence VALUES(?,?)",(oid,json.dumps({
                'rvol':None,'valid_activity_baseline':{'value':False,'provenance':'UNRESOLVED: no method'}})))
            db.execute("INSERT INTO semantic_shadow VALUES(?,?)",(oid,json.dumps({
                'same_clock_volume_sample_count':0,'observed_same_clock_volume_ratio':None})))
            diag=semantic_blockers(db)
            self.assertEqual(diag['blockers_nonexclusive']['rvol_not_numeric'],1)
            self.assertEqual(diag['blockers_nonexclusive']['baseline_provenance_unresolved'],1)
            self.assertEqual(diag['blockers_nonexclusive']['no_same_clock_history'],1)
            db.close()

    def test_live_retention_challenger_is_separate_and_prospective(self):
        from radar.retention_shadow import select, observe
        db=sqlite3.connect(':memory:')
        scout_init(db)
        db.execute("CREATE TABLE production_alerts(symbol TEXT)")
        session='2026-10-05'
        ts='2026-10-05T14:00:00+00:00'
        for symbol,selected,pct in [('WIN',1,5),('LOSS',1,3),('NEVER',0,4),('ALREADY',1,2)]:
            db.execute("INSERT INTO scout_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (1,session,symbol,ts,pct,0,0,0,'latestTrade',1,1,1,1,selected,0))
        db.execute("INSERT INTO scout_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (2,session,'ALREADY','2026-10-05T14:03:00+00:00',35,0,0,0,'latestTrade',1,1,1,1,0,0))
        db.commit()
        now=datetime.fromisoformat('2026-10-05T14:05:00+00:00')
        features={s:{'change_pct':5} for s in ('WIN','LOSS','NEVER','ALREADY')}
        chosen=select(db,session,3,features,[],now,60,10)
        self.assertEqual(set(chosen),{'WIN','LOSS'})
        calls=[]
        def fetch(url,headers):
            calls.append(url)
            return {'WIN':{'latestTrade':{'p':11,'t':'2026-10-05T14:04:00+00:00'}},
                    'LOSS':{'latestTrade':{'p':9,'t':'2026-10-05T12:00:00+00:00'}}},'2026-10-05T14:05:00+00:00'
        out=observe(db,3,session,features,[],now,{},'iex',fetch)
        self.assertEqual(out,{'status':'SHADOW_ONLY_NOT_BUY','selected':2,'valid':1})
        self.assertEqual(len(calls),1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM retention_shadow_observations").fetchone()[0],2)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM production_alerts").fetchone()[0],0)
        self.assertEqual(select(db,session,3,features,['WIN','LOSS'],now),[])

    def test_retention_shadow_replay_uses_only_past_selections(self):
        from radar.winner_recall_report import _retention_shadow_replay
        def row(run, minute, pct, selected=0):
            return {'run_id':run,'retrieval_ts':f'2026-10-05T14:{minute:02d}:00+00:00',
                    'change_pct':pct,'selected':selected}
        groups={
            ('2026-10-05','WIN'):[row(1,0,3,1),row(2,5,5),row(3,10,35),row(4,15,55)],
            ('2026-10-05','LOSE'):[row(1,0,2,1),row(2,5,1),row(3,10,0)],
            ('2026-10-05','NEVER_SELECTED'):[row(1,0,2),row(2,5,4),row(3,10,40)],
            ('2026-10-05','LATE'):[row(1,0,31),row(2,5,5,1),row(3,10,6)],
        }
        out=_retention_shadow_replay(groups,windows=(60,),caps=(2,))
        result=out['scenarios'][0]
        self.assertEqual(result['extra_deep_observation_slots'],3)
        self.assertEqual(result['held_with_later_observed_30'],1)
        self.assertEqual(result['held_with_later_observed_50'],1)
        self.assertEqual(result['unique_held_symbol_sessions'],2)
        self.assertEqual(result['max_extra_slots_in_cycle'],2)
        self.assertEqual(out['status'],'COUNTERFACTUAL_SHADOW_ROUTING_ONLY_NOT_BUY')

    def test_early_shortlist_outcomes_counts_nonwinners_and_avoids_lookahead(self):
        from radar.winner_recall_report import _early_shortlist_outcomes
        def row(ts, pct, selected=0):
            return {'retrieval_ts':ts, 'change_pct':pct, 'selected':selected}
        day='2026-10-05'
        groups={
            (day,'WIN'):[row('2026-10-05T14:00:00+00:00',3,1),
                         row('2026-10-05T14:05:00+00:00',31),
                         row('2026-10-05T14:10:00+00:00',52)],
            (day,'LOSE'):[row('2026-10-05T14:00:00+00:00',4,1),
                          row('2026-10-05T14:05:00+00:00',-1)],
            (day,'LATE'):[row('2026-10-05T14:00:00+00:00',40),
                          row('2026-10-05T14:05:00+00:00',5,1),
                          row('2026-10-05T14:10:00+00:00',50)],
            ('2026-10-08','OPEN'):[row('2026-10-08T14:00:00+00:00',2,1)],
        }
        now=datetime(2026,10,8,15,0,tzinfo=timezone.utc)
        out=_early_shortlist_outcomes(groups,now)
        self.assertEqual(out['finalized_selected_sessions'],2)
        self.assertEqual(out['pending_selected_sessions'],1)
        self.assertEqual(out['finalized_observed_30_after_selection'],1)
        self.assertEqual(out['finalized_observed_50_after_selection'],1)
        self.assertEqual(out['observed_50_rate_finalized'],0.5)
        self.assertNotIn('LATE',[x['symbol'] for x in out['cases']])
        self.assertEqual(next(x for x in out['cases'] if x['symbol']=='OPEN')['status'],
                         'PENDING_SESSION_CLOSE')

    def test_multi_engine_ranker_adds_sub10_precursor_without_changing_base(self):
        features={
          'BASE': {'retrieval_ts':'2026-10-05T14:00:00+00:00','change_pct':5.0,'acceleration':0.1,'impulse':0.001,'turnover':0.01,'route_source':'latestTrade'},
          'FAST': {'retrieval_ts':'2026-10-05T14:00:00+00:00','change_pct':4.0,'acceleration':2.0,'impulse':0.020,'turnover':0.05,'route_source':'latestTrade'},
          'LATE': {'retrieval_ts':'2026-10-05T14:00:00+00:00','change_pct':12.0,'acceleration':5.0,'impulse':0.050,'turnover':0.10,'route_source':'latestTrade'},
          'QUIET': {'retrieval_ts':'2026-10-05T14:00:00+00:00','change_pct':1.0,'acceleration':0.0,'impulse':0.0,'turnover':0.0001,'route_source':'latestTrade'},
        }
        scores,high_recall,extras=multi_engine_evaluate(features,['BASE'],extra_limit=1,watch_rank_limit=80)
        self.assertIn('FAST',scores)
        self.assertNotIn('LATE',scores)
        self.assertEqual(extras,['FAST'])
        self.assertTrue(scores['FAST']['dual_selected'])

    def test_multi_engine_watchpool_persists_repeated_precursor(self):
        db=open_db(':memory:'); multi_engine_init(db)
        features={'FAST':{'retrieval_ts':'2026-10-05T14:00:00+00:00','change_pct':4.0,'acceleration':2.0,'impulse':0.02,'turnover':0.05,'route_source':'latestTrade'}}
        scores,_,extras=multi_engine_evaluate(features,[],extra_limit=1)
        multi_engine_record(db,1,'2026-10-05',features,scores,[],extras)
        features['FAST']['retrieval_ts']='2026-10-05T14:05:00+00:00'
        multi_engine_record(db,2,'2026-10-05',features,scores,[],extras)
        row=db.execute("SELECT seen_count,peak_score FROM multi_engine_watchpool WHERE session='2026-10-05' AND symbol='FAST'").fetchone()
        self.assertEqual(row[0],2)
        self.assertGreaterEqual(row[1],0)

    def test_post_08_source_time_semantics(self):
        from radar.health import _source_at_or_after
        cutoff = '2026-10-08T12:00:00+00:00'
        self.assertFalse(_source_at_or_after('2026-10-08T11:59:00Z', cutoff))
        self.assertTrue(_source_at_or_after('2026-10-08T12:00:00Z', cutoff))
        self.assertTrue(_source_at_or_after('2026-10-08T12:02:00Z', cutoff))
        self.assertFalse(_source_at_or_after('invalid', cutoff))
        self.assertFalse(_source_at_or_after(None, cutoff))
        self.assertFalse(_source_at_or_after('2026-10-08T12:02:00', cutoff))

    def test_v0412_converted_symbols_default_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'radar.sqlite3'
            db = open_db(path)
            db.execute("""CREATE TABLE v0412_premarket_route (
                symbol TEXT, observed_ts TEXT, session TEXT, status TEXT
            )""")
            db.execute(
                "INSERT INTO runs(started,finished,status) VALUES(?,?,?)",
                ('2026-10-08T12:05:00+00:00',
                 '2026-10-08T12:05:10+00:00', 'MONITOR_OK')
            )
            db.commit()
            db.close()
            report = health_build(path)
            conversion = report['v0412_session_iex_conversion']
            self.assertEqual(conversion['converted_symbols'], [])
            self.assertEqual(conversion['valid_source_after_08_et'], 0)

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
