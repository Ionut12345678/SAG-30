"""Execute the actual publication shell against a local bare Git remote."""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from radar.checkpoint import prepare, restore_git

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.remote=self.root/'remote.git'
        self.checkout=self.root/'checkout';self.checkout.mkdir()
        self.git(['init','--bare','-q',str(self.remote)])
        self.git(['init','-q',str(self.checkout)])
        self.git(['config','user.name','Test'],self.checkout)
        self.git(['config','user.email','test@example.invalid'],self.checkout)
        (self.checkout/'seed').write_text('initial')
        self.git(['add','seed'],self.checkout);self.git(['commit','-qm','seed'],self.checkout)
        self.git(['remote','add','origin',str(self.remote)],self.checkout)
        self.git(['push','-q','origin','HEAD:radar-state'],self.checkout)
        self.base=self.git(['rev-parse','HEAD'],self.checkout).strip()
        self.state=self.checkout/'state';self.state.mkdir()
        self.db=self.state/'radar.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY, first_seen TEXT)')
            db.execute("INSERT INTO audit VALUES(1,'immutable')")
        health=self.state/'health.json';health.write_text('{"health":"PASS"}')
        prepare(self.db,self.state/'checkpoint',health,self.base,'test')
        text=Path('.github/workflows/radar.yml').read_text()
        block=text.split('      - name: Persist audit state and heartbeat\n',1)[1].split('\n      - name:',1)[0]
        self.script='\n'.join(line[10:] for line in block.split('        run: |\n',1)[1].splitlines() if line.startswith('          '))
        self.script=self.script.replace('/tmp/radar-state',str(self.root/'out')).replace('${{ steps.restore.outputs.commit }}',self.base).replace('sleep $((attempt * 5))',':')
        for name in ['early_paper_extra_report_v11','early_paper_outcome_report_v12','early_paper_diagnostic_v13','early_paper_momentum_shadow_v14','early_paper_matched_outcome_v15','semantic_shadow_report','candidate_v034_report','winner_recall_report','multi_engine_report']:
            (self.state/(name+'.json')).write_text('{}')
        self.env=dict(os.environ,GITHUB_WORKSPACE=str(self.checkout),GITHUB_SERVER_URL=str(self.root),GITHUB_REPOSITORY='remote',GITHUB_STEP_SUMMARY=str(self.root/'summary'))
    def tearDown(self):self.temp.cleanup()
    def git(self,args,cwd=None):
        return subprocess.check_output(['git',*args],cwd=cwd,text=True,stderr=subprocess.PIPE)
    def publish(self):
        return subprocess.run(['bash','-euo','pipefail','-c',self.script],cwd=self.checkout,env=self.env,text=True,capture_output=True)
    def test_publish_all_rows_with_manifest_and_heartbeat(self):
        result=self.publish();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('SAG30_CHECKPOINT_PUSH_PASS',result.stdout)
        restored=self.root/'restored.db'
        restore_git(self.remote,'refs/heads/radar-state',restored)
        with sqlite3.connect(restored) as db:self.assertEqual(db.execute('SELECT * FROM audit').fetchall(),[(1,'immutable')])
        health=json.loads(self.git(['--git-dir='+str(self.remote),'show','radar-state:health.json']))
        self.assertEqual(health['checkpoint']['publication'],'PREPARED_NOT_CONFIRMED')
    def test_concurrent_writer_cannot_be_overwritten(self):
        (self.checkout/'seed').write_text('second writer')
        self.git(['add','seed'],self.checkout);self.git(['commit','-qm','concurrent'],self.checkout)
        self.git(['push','-q','origin','HEAD:radar-state'],self.checkout)
        peer=self.git(['rev-parse','HEAD'],self.checkout).strip()
        result=self.publish();self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.git(['--git-dir='+str(self.remote),'rev-parse','radar-state']).strip(),peer)
        self.assertTrue((self.state/'checkpoint/checkpoint.json').is_file())
    def test_push_acknowledgement_loss_is_confirmed_without_overwrite(self):
        tools=self.root/'tools';tools.mkdir()
        shim=tools/'git'
        real=shutil.which('git')
        shim.write_text('#!/bin/bash\nif [ "$1" = push ] && [ ! -f "$ACK_MARKER" ]; then\n'+real+' "$@"\nrc=$?\nif [ "$rc" -eq 0 ]; then touch "$ACK_MARKER"; exit 1; fi\nexit "$rc"\nfi\nexec '+real+' "$@"\n')
        shim.chmod(0o755)
        self.env.update(PATH=str(tools)+os.pathsep+os.environ['PATH'],ACK_MARKER=str(self.root/'ack'))
        result=self.publish();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('SAG30_CHECKPOINT_PUSH_PASS',result.stdout)
