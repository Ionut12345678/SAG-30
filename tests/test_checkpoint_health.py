import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from radar.core import open_db, record
from radar.scout import init as scout_init
from radar.fast_path_shadow import init as fast_init
from radar.health import build

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'radar.sqlite3'
        self.db=open_db(self.path);scout_init(self.db);fast_init(self.db)
        self.db.execute("INSERT INTO runs(id,started,finished,status) VALUES(1,'2026-10-12T13:00:00+00:00','2026-10-12T13:00:10+00:00','MONITOR_OK')")
        self.db.execute("INSERT INTO runs(id,started,finished,status) VALUES(2,'2026-10-12T13:08:00+00:00','2026-10-12T13:08:10+00:00','MONITOR_DATA_GAP')")
        record(self.db,2,'TEST',{},'2026-10-12T13:08:00+00:00','2026-10-12T13:08:10+00:00',900)
        self.db.execute("INSERT INTO scout_runs VALUES(2,'2026-10-12T13:08:00+00:00','2026-10-12T13:08:10+00:00',3185,0,0,0,1,2)")
        self.db.commit()
        self.now=datetime(2026,10,12,13,10,tzinfo=timezone.utc)
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def test_data_gap_and_missed_cadence_are_not_pass(self):
        health=build(self.path,now=self.now)
        self.assertEqual(health['health'],'DEGRADED')
        self.assertEqual(health['fast_scout']['status'],'DATA_GAP')
        self.assertEqual(health['observations']['ok'],0)
        self.assertEqual(health['cadence']['status'],'MISSED_TARGET')
        self.assertEqual(health['cadence_gap_seconds'],480)
    def test_fast_path_failure_is_independent(self):
        health=build(self.path,fast_path_outcome='failure',now=self.now)
        self.assertEqual(health['health'],'FAIL')
        self.assertEqual(health['fast_path']['status'],'FAIL')
        self.assertEqual(health['evidence_health'],'UNEXPECTED_MODEL_DATA_GAP')
    def test_premarket_skip_is_not_live_evidence(self):
        health=build(self.path,fast_path_outcome='success',fast_path_mode='PREMARKET_ROUTING_ONLY',now=self.now)
        self.assertEqual(health['fast_path']['status'],'EXPECTED_PREMARKET_ROUTING_ONLY')
        self.assertEqual(health['fast_path']['current_cycle_events'],0)
    def test_fast_path_current_event_survives_round_trip(self):
        self.db.execute("INSERT INTO fast_path_events(session,symbol,retrieval_ts,source,state) VALUES('2026-10-12','TEST','2026-10-12T13:09:00+00:00','IEX','DISCOVERED')")
        self.db.commit()
        health=build(self.path,fast_path_outcome='success',now=self.now)
        self.assertEqual(health['fast_path']['status'],'CURRENT_SHADOW_EVIDENCE')
        self.assertEqual(health['fast_path']['current_cycle_events'],1)
        self.assertEqual(health['health'],'DEGRADED')
    def test_stale_heartbeat_is_explicit(self):
        health=build(self.path,now=datetime(2026,10,12,15,tzinfo=timezone.utc))
        self.assertFalse(health['checkpoint_is_current_cycle'])
        self.assertEqual(health['checkpoint_freshness'],'STALE')
        self.assertNotEqual(health['health'],'PASS')

    def test_negative_cadence_gap_is_never_within_target(self):
        self.db.execute("UPDATE runs SET started='2026-10-12T13:09:00+00:00' WHERE id=1")
        self.db.commit()
        health=build(self.path,now=self.now)
        self.assertEqual(health['cadence']['status'],'INVALID_SEQUENCE')
        self.assertEqual(health['cadence_gap_seconds'],-60)

    def test_failure_before_fast_path_table_creation_is_explicit(self):
        self.db.execute('DROP TABLE fast_path_events');self.db.commit()
        health=build(self.path,now=self.now,fast_path_outcome='failure')
        self.assertEqual(health['fast_path']['status'],'FAIL')
        self.assertEqual(health['health'],'FAIL')

    def test_storage_alert_does_not_create_market_data_gap(self):
        from radar.checkpoint import prepare
        from unittest.mock import patch
        import json
        self.db.execute("UPDATE runs SET started='2026-10-12T13:03:00+00:00' WHERE id=1")
        self.db.execute("UPDATE runs SET status='MONITOR_OK' WHERE id=2")
        self.db.execute('UPDATE scout_runs SET eligible_count=100,selected_count=1 WHERE run_id=2')
        self.db.execute('DELETE FROM evaluations')
        self.db.execute('DELETE FROM observations')
        record(self.db,2,'TEST',{'latestTrade':{'p':10.5,'t':'2026-10-12T13:08:00Z'},'prevDailyBar':{'c':10,'t':'2026-10-09T20:00:00Z'}},'2026-10-12T13:08:00+00:00','2026-10-12T13:08:10+00:00',900)
        self.db.commit()
        health=build(self.path,now=self.now)
        self.assertEqual(health['health'],'PASS')
        output=self.path.parent/'health.json';output.write_text(json.dumps(health))
        with patch('radar.checkpoint.size_status',return_value='CRITICAL_90_MIB'):
            prepare(self.path,self.path.parent/'parts',health_path=output)
        result=json.loads(output.read_text())
        self.assertEqual(result['health'],'DEGRADED')
        self.assertEqual(result['fast_scout']['status'],'PASS')
        self.assertEqual(result['observations']['data_quality'],0)

    def test_successful_minute_loop_without_current_evidence_is_degraded(self):
        self.db.execute("UPDATE runs SET started='2026-10-12T13:03:00+00:00' WHERE id=1")
        self.db.execute("UPDATE runs SET status='MONITOR_OK' WHERE id=2")
        self.db.execute('UPDATE scout_runs SET eligible_count=100,selected_count=1 WHERE run_id=2')
        self.db.execute('DELETE FROM evaluations')
        self.db.execute('DELETE FROM observations')
        record(self.db,2,'TEST',{'latestTrade':{'p':10.5,'t':'2026-10-12T13:08:00Z'},'prevDailyBar':{'c':10,'t':'2026-10-09T20:00:00Z'}},'2026-10-12T13:08:00+00:00','2026-10-12T13:08:10+00:00',900)
        self.db.commit()
        health=build(self.path,now=self.now,fast_path_outcome='success',fast_path_mode='MINUTE_LOOP')
        self.assertEqual(health['fast_scout']['status'],'PASS')
        self.assertEqual(health['fast_path']['status'],'NO_CURRENT_EVIDENCE')
        self.assertEqual(health['health'],'DEGRADED')
