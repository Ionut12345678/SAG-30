import unittest
from radar.core import open_db, record
from radar.model import evaluate, verify_spec

class ModelTests(unittest.TestCase):
    def setUp(self):
        self.db = open_db(':memory:')
        self.run = self.db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid

    def observe(self, minute, price, facts=True, replay=False):
        stamp = f'2026-10-05T14:{minute:02}:00+00:00'
        record(self.db,self.run,'TEST',{'latestTrade':{'p':price,'t':stamp},'prevDailyBar':{'c':10,'t':'2026-10-02T20:00:00Z'}},stamp,stamp,900)
        oid = self.db.execute('SELECT max(id) FROM observations').fetchone()[0]
        evidence = {'symbol':'TEST','source_ts':stamp,'lane':'FRESH','rvol':4}
        if facts:
            for name in ('valid_activity_baseline','lane_classification','price_conversion','acceptance_reclaim','no_absorption','acceptance_still_valid'):
                evidence[name] = {'value':True,'provenance':'synthetic test evidence'}
        return evaluate(self.db,oid,evidence,replay)

    def test_frozen_hash(self):
        verify_spec()

    def test_activity_alone_not_hot(self):
        self.assertNotEqual(self.observe(0,10.5,False),'EARLY-HOT')
        self.assertNotEqual(self.observe(5,11,False),'EARLY-HOT')

    def test_subsequent_expansion_only(self):
        self.assertEqual(self.observe(0,10.5),'RADAR/WATCH')
        self.assertEqual(self.observe(5,10.6),'EARLY-HOT')
        row = self.db.execute('SELECT retrieval_ts,band,early_credit FROM signals').fetchone()
        self.assertEqual(row,('2026-10-05T14:05:00+00:00','IDEAL',1))
        self.observe(10,13)
        self.assertEqual(self.db.execute('SELECT target FROM milestones').fetchone()[0],30)
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0],1)

    def test_late_zero_credit(self):
        self.observe(0,11)
        self.assertEqual(self.observe(5,12),'LATE-RADAR')
        self.assertEqual(self.db.execute('SELECT early_credit FROM signals').fetchone()[0],0)

    def test_replay_no_credit_or_alert(self):
        self.observe(0,10.5,replay=True)
        self.observe(5,10.6,replay=True)
        self.assertEqual(self.db.execute('SELECT early_credit FROM signals').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)

    def test_no_high_wait(self):
        self.observe(0,10.5)
        self.assertEqual(self.observe(5,10.5),'RADAR/WATCH')
        self.assertEqual(self.observe(10,10.5),'RADAR/WATCH')
        self.assertEqual(self.db.execute('SELECT count(*) FROM signals').fetchone()[0],0)

    def test_first_seen_immutable(self):
        self.observe(0,10.5)
        self.observe(5,10.6)
        self.assertEqual(self.db.execute('SELECT first_seen,first_radar_seen FROM model_state').fetchone(),('2026-10-05T14:00:00+00:00',)*2)
        with self.assertRaises(Exception):
            self.db.execute("UPDATE model_state SET first_seen='yesterday'")

    def test_missing_semantic_proof_waits(self):
        self.observe(0,10.5)
        self.assertNotEqual(self.observe(5,11,False),'EARLY-HOT')
        self.assertEqual(self.db.execute('SELECT count(*) FROM signals').fetchone()[0],0)

    def test_report_preserves_unknown_metrics(self):
        from radar.report import report
        self.observe(0,10.5)
        self.observe(5,10.6)
        data = report(self.db)
        self.assertEqual(data['hot_below_10'],1)
        self.assertTrue(data['false_HOT'].startswith('UNKNOWN'))
        self.assertEqual(data['observation_gap_seconds'],[300])

    def test_other_lanes_without_required_gates_unknown_wait(self):
        for lane in ('SECOND_IMPULSE','OVERNIGHT'):
            db = open_db(':memory:')
            run = db.execute("INSERT INTO runs(started,status) VALUES('now','RUNNING')").lastrowid
            for minute,price in ((0,10.5),(5,10.6)):
                stamp = f'2026-10-05T14:{minute:02}:00+00:00'
                record(db,run,'TEST',{'latestTrade':{'p':price,'t':stamp},'prevDailyBar':{'c':10,'t':'2026-10-02T20:00:00Z'}},stamp,stamp,900)
                evidence = {'symbol':'TEST','source_ts':stamp,'lane':lane,'rvol':4}
                for name in ('valid_activity_baseline','lane_classification','price_conversion','acceptance_reclaim','no_absorption','acceptance_still_valid'):
                    evidence[name] = {'value':True,'provenance':'synthetic'}
                self.assertEqual(evaluate(db,minute//5+1,evidence),'RADAR/WATCH')
            self.assertEqual(db.execute('SELECT count(*) FROM signals').fetchone()[0],0)

    def test_conflicting_snapshot_blocks(self):
        stamp = '2026-10-05T14:00:00+00:00'
        record(self.db,self.run,'TEST',{'latestTrade':{'p':10.5,'t':stamp},'prevDailyBar':{'c':10,'t':'2026-10-02T20:00:00Z'},'data_quality_conflict':True},stamp,stamp,900)
        self.assertEqual(evaluate(self.db,1),'UNKNOWN/DATA_QUALITY')

    def test_stored_evidence_and_hash(self):
        import hashlib
        self.observe(0,10.5)
        payload, digest = self.db.execute('SELECT payload,payload_hash FROM evidence').fetchone()
        self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(),digest)
