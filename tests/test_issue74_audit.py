import hashlib
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from radar.core import open_db,record
from radar.scout import init
from radar.prospective_audit import build

class ProspectiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'radar.sqlite3'
        self.db=open_db(self.path);init(self.db)
        self.db.execute("INSERT INTO runs VALUES(1,'2026-10-12T14:00:00+00:00',NULL,'DISCOVERY_OK',NULL)")
        self.now=datetime(2026,10,12,16,tzinfo=timezone.utc)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def sample(self,symbol,ts,pct,quality='OK'):
        snapshot={'latestTrade':{'p':10*(1+pct/100),'t':ts},'prevDailyBar':{'c':10,'t':'2026-10-09T20:00:00Z'}} if quality=='OK' else {}
        record(self.db,1,symbol,snapshot,ts,ts,900)
        self.db.commit()
    def audit(self,watch=None):return build(self.path,'2026-10-12',watch,self.now)
    def test_later_move_is_not_backdated_and_database_unchanged(self):
        self.sample('A','2026-10-12T14:00:00Z',4)
        self.sample('A','2026-10-12T14:10:00Z',31)
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        c=self.audit()['cohorts'][0]
        self.assertEqual(c['detection_band'],'EXCELLENT')
        self.assertEqual(c['early_credit'],0)
        self.assertEqual(c['observed_crossings']['30']['lead_seconds_from_discovery'],600)
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_late_first_detection_gets_no_prospective_30_credit(self):
        self.sample('A','2026-10-12T14:00:00Z',35)
        self.sample('A','2026-10-12T14:10:00Z',40)
        c=self.audit()['cohorts'][0]
        self.assertTrue(c['late_detection']);self.assertIsNone(c['observed_crossings']['30'])
    def test_bad_data_and_future_retrieval_are_not_outcomes(self):
        self.sample('A','2026-10-12T14:00:00Z',4)
        self.sample('A','2026-10-12T14:10:00Z',50,'BAD')
        self.sample('A','2026-10-12T17:00:00Z',50)
        result=self.audit();c=result['cohorts'][0]
        self.assertIn('missing_or_invalid_source_timestamp',result['rejection_reasons'])
        self.assertEqual(result['run_health'][0]['status'],'DISCOVERY_OK')
        self.assertEqual(c['outcome'],'CENSORED_NO_FOLLOWUP')
        self.assertEqual(c['false_positive'],'UNKNOWN_CENSORED')
    def test_watch_uses_actual_capture_availability(self):
        self.sample('A','2026-10-12T14:00:00Z',4)
        self.sample('A','2026-10-12T14:10:00Z',31)
        journal=Path(self.tmp.name)/'watch.jsonl'
        journal.write_text(json.dumps({'session':'2026-10-12','symbol':'A','ts':'2026-10-12T14:00:00Z','captured_at_utc':'2026-10-12T14:11:00Z'})+'\n')
        c=self.audit(journal)['cohorts'][0]
        self.assertIsNone(c['observed_crossings']['30']['watch_lead_seconds'])
        self.assertEqual(c['first_watch']['captured_at_utc'],'2026-10-12T14:11:00Z')
    def test_no_inferred_watch_and_no_false_positive_claim(self):
        self.sample('A','2026-10-12T14:00:00Z',4);self.sample('A','2026-10-12T14:10:00Z',5)
        self.db.execute('CREATE TABLE v049_state(session TEXT,symbol TEXT,first_watch_ts TEXT,last_eval_ts TEXT)')
        self.db.execute("INSERT INTO v049_state VALUES('2026-10-12','A','2026-10-12T14:00:00Z','2026-10-12T14:10:00Z')");self.db.commit()
        c=self.audit()['cohorts'][0]
        self.assertEqual(c['stored_precursor_context']['first_watch_ts'],'2026-10-12T14:00:00Z')
        self.assertEqual(c['precursor_event_provenance'],'UNKNOWN_MUTABLE_STATE_NOT_IMMUTABLE_EVENT')
        self.assertIsNone(c['first_watch']);self.assertEqual(c['outcome'],'CENSORED_NO_OBSERVED_30')
    def test_scout_denominator_retains_not_selected_symbols_and_unknown_source(self):
        self.db.execute("INSERT INTO scout_history VALUES(1,'2026-10-12','UNSELECTED','2026-10-12T14:00:00Z',4,0,0,0,'minuteBar',1,1,1,1,0,0)")
        self.db.commit();c=self.audit()['cohorts'][0]
        self.assertIsNone(c['first_deep_observation']);self.assertIsNone(c['first_discovery_source_ts'])
        self.assertEqual(c['outcome'],'CENSORED_NO_FOLLOWUP')
    def test_duplicate_watch_rejected(self):
        journal=Path(self.tmp.name)/'watch.jsonl';row=json.dumps({'session':'2026-10-12','symbol':'A','captured_at_utc':'2026-10-12T14:00:00Z'})+'\n'
        journal.write_text(row*2)
        with self.assertRaises(ValueError):self.audit(journal)
    def test_old_ok_row_with_future_source_is_rejected(self):
        self.sample('A','2026-10-12T14:00:00Z',4)
        self.sample('A','2026-10-12T14:10:00Z',50)
        self.db.execute("UPDATE observations SET source_ts='2026-10-12T15:00:00Z' WHERE id=2");self.db.commit()
        result=self.audit()
        self.assertEqual(result['counts']['invalid_stored_ok_source_samples'],1)
        self.assertIsNone(result['cohorts'][0]['observed_crossings']['50'])

class PublishedAuditTests(unittest.TestCase):
    def test_verifies_real_git_manifest_and_journal_before_receipt(self):
        import os,subprocess
        from radar.checkpoint import prepare
        from radar.checkpoint_audit import audit
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);dbpath=root/'source.sqlite3';db=open_db(dbpath);db.close()
            journals=root/'journals';journals.mkdir()
            (journals/'shadow_first_watch.jsonl').write_text('{"immutable":true}\n')
            repo=root/'repo';prepare(dbpath,repo,journal_dir=journals)
            def run(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.PIPE)
            run('init','-q');run('config','user.name','Audit test');run('config','user.email','audit@example.invalid');run('add','.');run('commit','-qm','snapshot')
            run('branch','radar-state');run('remote','add','origin',str(repo))
            previous=os.getcwd()
            try:
                os.chdir(repo)
                report=audit('HEAD')
                self.assertEqual(report['publication'],'REMOTE_REF_CONFIRMED')
                self.assertTrue(report['journal_inventory_verified'])
                (repo/'shadow_first_watch.jsonl').write_text('rewritten\n');run('add','.');run('commit','-qm','corrupt')
                with self.assertRaises(ValueError):audit('HEAD')
            finally:os.chdir(previous)
