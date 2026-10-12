"""Read-only verification of published storage, separate from prepared health."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from .checkpoint import restore_git, check_db, MANIFEST, JOURNALS


def git(*args):
    return subprocess.check_output(['git',*args])


def audit(ref, remote='origin'):
    commit=git('rev-parse',ref+'^{commit}').decode().strip()
    manifest=json.loads(git('show',commit+':'+MANIFEST))
    with tempfile.TemporaryDirectory(prefix='sag30-published-audit-') as root:
        db=Path(root)/'radar.sqlite3'
        restore_git(Path.cwd(),commit,db)
        counts=check_db(db)
        for journal in manifest.get('journals',[]):
            if journal['name'] not in JOURNALS: raise ValueError('invalid journal name')
            raw=git('show',commit+':'+journal['name'])
            if len(raw)!=journal['bytes'] or hashlib.sha256(raw).hexdigest()!=journal['sha256']:
                raise ValueError('published journal integrity failure')
    receipt=git('ls-remote',remote,'refs/heads/radar-state').decode().split()
    remote_head=receipt[0] if receipt else None
    return {'publication':'REMOTE_REF_CONFIRMED' if remote_head==commit else 'VERIFIED_HISTORICAL_SNAPSHOT',
        'verified_commit':commit,'remote_head_at_check':remote_head,
        'compressed_bytes':manifest['compressed_bytes'],'part_count':len(manifest['parts']),
        'table_counts':counts,'journal_inventory_verified': 'journals' in manifest,
        'audit_retention':manifest['audit_retention'],
        'warning':'Receipt is checked at report time; embedded health was prepared before push. No quota or indefinite retention guarantee.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--ref',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();Path(a.out).write_text(json.dumps(audit(a.ref),indent=2,sort_keys=True)+'\n')

if __name__=='__main__':main()
