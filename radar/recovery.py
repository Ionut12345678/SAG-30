"""Recover a failed publication's full snapshot before collecting another cycle.

Only artifacts from radar.yml with exactly the restored parent commit qualify.
No rescans, historical backfill, credential dumps, or trading operations.
"""
import argparse
import json
import os
import sqlite3
from contextlib import closing
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
import zipfile
from pathlib import Path
from .checkpoint import MANIFEST, JOURNALS, file_sha, restore_directory, validate_manifest

# The following tables are append-only prospective evidence in the existing app.
# Mutable routing state, delivery attempts and open-run status are not compared.
AUDIT_TABLES = ('observations', 'evidence', 'semantic_shadow', 'scout_history',
                'scout_promotions', 'fast_path_events', 'signals', 'milestones',
                'candidate_v034_events', 'candidate_v034r2_events',
                'candidate_v034_signals', 'candidate_v034r2_signals',
                'fast_path_v047_observations', 'fast_path_v048_observations')


def assert_audit_extension(baseline, candidate):
    def quote(name):
        return '"' + name.replace('"', '""') + '"'
    with closing(sqlite3.connect(Path(candidate).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('ATTACH DATABASE ? AS baseline',(Path(baseline).resolve().as_uri()+'?mode=ro',))
        existing={row[0] for row in db.execute("SELECT name FROM baseline.sqlite_master WHERE type='table'")}
        current={row[0] for row in db.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
        for table in AUDIT_TABLES:
            if table not in existing:
                continue
            if table not in current:
                raise ValueError('Recovery removed published audit table: '+table)
            columns=[row[1] for row in db.execute('PRAGMA baseline.table_info('+quote(table)+')')]
            new_columns={row[1] for row in db.execute('PRAGMA main.table_info('+quote(table)+')')}
            if not set(columns)<=new_columns:
                raise ValueError('Recovery removed published audit columns: '+table)
            predicates=' AND '.join('n.'+quote(col)+' IS b.'+quote(col) for col in columns)
            missing=db.execute('SELECT 1 FROM baseline.'+quote(table)+' b WHERE NOT EXISTS (SELECT 1 FROM main.'+quote(table)+' n WHERE '+predicates+') LIMIT 1').fetchone()
            if missing:
                raise ValueError('Recovery deleted or changed published audit evidence: '+table)
        if 'model_state' in existing:
            if 'model_state' not in current:
                raise ValueError('Recovery removed published model first_seen state')
            columns={row[1] for row in db.execute('PRAGMA baseline.table_info(model_state)')}
            protected=[col for col in ('first_seen','first_radar_seen','first_radar_pct') if col in columns]
            predicates=' OR '.join('(b.'+quote(col)+' IS NOT NULL AND n.'+quote(col)+' IS NOT b.'+quote(col)+')' for col in protected)
            if predicates and db.execute('SELECT 1 FROM baseline.model_state b LEFT JOIN main.model_state n ON n.symbol=b.symbol WHERE n.symbol IS NULL OR '+predicates+' LIMIT 1').fetchone():
                raise ValueError('Recovery changed published first_seen/first_radar state')


def verify_journals(root, manifest, journal_dir):
    # v1 artifacts predating journal hashes remain readable, but may not discard
    # an existing immutable journal. New artifacts also verify length/SHA-256.
    declared={row['name']:row for row in manifest.get('journals',[])}
    for name in JOURNALS:
        candidate=Path(root)/name
        if 'journals' in manifest and candidate.exists() and name not in declared:
            raise ValueError('Recovery journal not declared in checkpoint: '+name)
        if name in declared:
            expected=declared[name]
            if not candidate.is_file() or candidate.stat().st_size!=expected['bytes'] or file_sha(candidate)!=expected['sha256']:
                raise ValueError('Recovery journal checksum/size mismatch: '+name)
        if journal_dir and name.endswith('.jsonl'):
            baseline=Path(journal_dir)/name
            if baseline.exists():
                if not candidate.exists():
                    raise ValueError('Recovery missing published first-WATCH journal: '+name)
                with baseline.open('rb') as old,candidate.open('rb') as new:
                    for block in iter(lambda:old.read(1024*1024),b''):
                        if new.read(len(block))!=block:
                            raise ValueError('Recovery rewrote published first-WATCH history: '+name)


def gh_json(path):
    return json.loads(subprocess.check_output(['gh','api',path], text=True))


def recover(repo, base_commit, destination, status_path, journal_dir=None, base_published_ts=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid repository identity')
    result = {'status': 'NO_COMPATIBLE_RECOVERY_ARTIFACT', 'base_commit': base_commit}
    # API failure is not equivalent to absence: fail closed rather than lose a failed cycle.
    def list_artifacts(name):
        found, page = [], 1
        while True:
            items = gh_json(f'repos/{repo}/actions/artifacts?name={name}&per_page=100&page={page}')['artifacts']
            found.extend(items)
            if len(items) < 100:
                return found
            page += 1
    def newer_than_base(artifact):
        return base_published_ts is None or datetime.fromisoformat(artifact['created_at'].replace('Z','+00:00')) > datetime.fromisoformat(base_published_ts.replace('Z','+00:00'))
    # Unreadable/corrupt forensic evidence must be adjudicated before another scan.
    for artifact in list_artifacts('sag30-checkpoint-forensic'):
        if newer_than_base(artifact):
            run = gh_json(f'repos/{repo}/actions/runs/{artifact['workflow_run']['id']}')
            if run['path'] == '.github/workflows/radar.yml' and run['head_branch'] == 'main':
                raise ValueError('Unresolved forensic checkpoint; restore/archive its audit data before scanning')
    artifacts = list_artifacts('sag30-checkpoint-recovery')
    for artifact in sorted(artifacts, key=lambda a: a['id'], reverse=True):
        if not newer_than_base(artifact):
            continue
        run_id = artifact['workflow_run']['id']
        run = gh_json(f'repos/{repo}/actions/runs/{run_id}')
        if run['path'] != '.github/workflows/radar.yml' or run['head_branch'] != 'main':
            continue
        if artifact['expired']:
            raise ValueError('Recent recovery artifact expired; audit recovery requires operator action')
        with tempfile.TemporaryDirectory(prefix='sag30-artifact-') as directory:
            root = Path(directory)
            archive = root / 'recovery.zip'
            with archive.open('wb') as dst:
                subprocess.run(['gh','api',f'repos/{repo}/actions/artifacts/{artifact["id"]}/zip'], stdout=dst, check=True)
            with zipfile.ZipFile(archive) as zipped:
                # Upload path is state/checkpoint; no arbitrary ZIP extraction.
                manifest = json.loads(zipped.read(MANIFEST))
                validate_manifest(manifest)
                if manifest.get('base_commit') != base_commit:
                    continue
                if str(manifest.get('workflow_run_id')) != str(run_id):
                    raise ValueError('Recovery artifact run identity mismatch')
                (root / MANIFEST).write_text(json.dumps(manifest))
                for part in manifest['parts']:
                    with zipped.open(part['name']) as src, (root / part['name']).open('wb') as dst:
                        shutil.copyfileobj(src,dst)
                for name in JOURNALS:
                    if name in zipped.namelist():
                        with zipped.open(name) as src, (root / name).open('wb') as dst:
                            shutil.copyfileobj(src,dst)
            verify_journals(root,manifest,journal_dir)
            candidate=root/'candidate.sqlite3'
            restore_directory(root,candidate)
            assert_audit_extension(destination,candidate)
            if any(Path(str(destination)+suffix).exists() for suffix in ('-wal','-shm')):
                raise ValueError('Refusing recovery over live WAL/SHM sidecars')
            # Move through a sibling file so os.replace remains atomic across filesystems.
            staged_path=None
            try:
                with tempfile.NamedTemporaryFile(dir=Path(destination).parent,delete=False) as staged:
                    staged_path=Path(staged.name)
                    with candidate.open('rb') as src:
                        shutil.copyfileobj(src,staged)
                os.replace(staged_path,destination)
            finally:
                if staged_path is not None:
                    staged_path.unlink(missing_ok=True)
            if journal_dir:
                Path(journal_dir).mkdir(parents=True,exist_ok=True)
                for name in JOURNALS:
                    if (root / name).exists():
                        shutil.copyfile(root / name,Path(journal_dir) / name)
            result = {'status': 'RESTORED_RECOVERY_ARTIFACT', 'base_commit': base_commit,
                      'artifact_id': artifact['id'], 'workflow_run_id': run_id,
                      'database_sha256': manifest['database_sha256']}
            print(f'SAG30_RECOVERY_PASS artifact={artifact["id"]} run={run_id}')
            break
    Path(status_path).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True)
    parser.add_argument('--base-commit',required=True)
    parser.add_argument('--base-published-ts')
    parser.add_argument('--out',required=True)
    parser.add_argument('--status',required=True)
    parser.add_argument('--journal-dir')
    args = parser.parse_args()
    recover(args.repo,args.base_commit,args.out,args.status,args.journal_dir,args.base_published_ts)
