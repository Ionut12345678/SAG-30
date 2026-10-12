"""Recover a failed publication's full snapshot before collecting another cycle.

Only artifacts from radar.yml with exactly the restored parent commit qualify.
No rescans, historical backfill, credential dumps, or trading operations.
"""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
import zipfile
from pathlib import Path
from .checkpoint import MANIFEST, restore_directory, validate_manifest

JOURNALS = ('shadow_first_watch.jsonl', 'shadow_watch_observations.jsonl', 'shadow_watch_status.json')


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
            restore_directory(root,destination)
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
