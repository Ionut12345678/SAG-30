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
