"""Lossless SQLite checkpoints with bounded Git blobs and atomic verified restore.

No row retention policy, schema migration, model evaluation, or production writes.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from .core import LABEL

MIB = 1024 * 1024
PART_BYTES = 64 * MIB
BLOB_LIMIT = 95 * MIB
MANIFEST = 'checkpoint.json'
FORMAT = 'sag30-sqlite-gzip-parts-v1'
JOURNALS = ('shadow_first_watch.jsonl', 'shadow_watch_observations.jsonl', 'shadow_watch_status.json')


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''):
            digest.update(block)
    return digest.hexdigest()


def size_status(size):
    if size >= 90 * MIB:
        return 'CRITICAL_90_MIB'
    if size >= 80 * MIB:
        return 'WARNING_80_MIB'
    return 'OK'


def check_db(path):
    # mode=ro prevents accidental initialization of a missing checkpoint.
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite checkpoint integrity check failed')
        schema = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        if not schema:
            raise ValueError('Checkpoint contains no tables')
        counts = {}
        for (name,) in schema:
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = db.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0]
        return counts


def prepare(db_path, output, health_path=None, base_commit=None, run_id=None, part_bytes=PART_BYTES, journal_dir=None):
    if not 0 < part_bytes < BLOB_LIMIT:
        raise ValueError('Each checkpoint part must be below the 95 MiB blob limit')
    db_path, output = Path(db_path), Path(output)
    if not db_path.is_file():
        raise ValueError('Audit database missing; refusing empty checkpoint')
    output.mkdir(parents=True, exist_ok=True)
    if (output / MANIFEST).exists() or list(output.glob('radar.sqlite3*')):
        raise ValueError('Use a fresh checkpoint output directory')
    with tempfile.TemporaryDirectory(prefix='sag30-snapshot-', dir=output.parent) as directory:
        snapshot = Path(directory) / 'radar.sqlite3'
        # Backup API includes committed WAL transactions; never gzip a live main file.
        with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        counts = check_db(snapshot)
        db_sha = file_sha(snapshot)
        compressed = Path(directory) / 'radar.sqlite3.gz'
        with snapshot.open('rb') as src, compressed.open('wb') as dst:
            with gzip.GzipFile(fileobj=dst, mode='wb', compresslevel=6, mtime=0, filename='') as zipped:
                shutil.copyfileobj(src, zipped, length=MIB)
        compressed_bytes = compressed.stat().st_size
        parts = []
        with compressed.open('rb') as stream:
            index = 0
            while block := stream.read(part_bytes):
                name = f'radar.sqlite3.gz.part-{index:05d}'
                (output / name).write_bytes(block)
                parts.append({'name': name, 'bytes': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
                index += 1
        journals = []
        if journal_dir:
            for name in JOURNALS:
                path = Path(journal_dir) / name
                if path.is_file():
                    shutil.copyfile(path, output / name)
                    journals.append({'name': name, 'bytes': (output / name).stat().st_size, 'sha256': file_sha(output / name)})
        manifest = {'format': FORMAT, 'created_ts': datetime.now(timezone.utc).isoformat(),
                    'base_commit': base_commit, 'workflow_run_id': run_id,
                    'database_bytes': snapshot.stat().st_size, 'database_sha256': db_sha,
                    'compressed_bytes': compressed_bytes, 'compressed_sha256': file_sha(compressed),
                    'part_limit_bytes': part_bytes, 'parts': parts, 'journals': journals, 'table_counts': counts,
                    'size_status': size_status(compressed_bytes), 'audit_retention': 'ALL_ROWS_NO_PRUNING'}
        # Manifest is the completion marker; failed preparations cannot appear complete.
        (output / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    if health_path:
        health = json.loads(Path(health_path).read_text())
        health['checkpoint'] = {key: manifest[key] for key in ('format','created_ts','database_bytes','compressed_bytes','size_status','database_sha256','workflow_run_id')}
        health['checkpoint'].update(part_count=len(parts), largest_part_bytes=max(p['bytes'] for p in parts),
                                    publication='PREPARED_NOT_CONFIRMED', audit_retention=manifest['audit_retention'])
        if manifest['size_status'] != 'OK' and health.get('health') == 'PASS':
            health['health'] = 'DEGRADED'
        # Emit the same augmented heartbeat locally and in the outgoing snapshot.
        content = json.dumps(health, indent=2, sort_keys=True) + '\n'
        Path(health_path).write_text(content)
        (output / 'health.json').write_text(content)
    if manifest['size_status'] != 'OK':
        print(f"::warning title=SAG-30 checkpoint {manifest['size_status']}::Total compressed checkpoint {compressed_bytes / MIB:.2f} MiB; all audit rows retained in {len(parts)} bounded parts. {LABEL}")
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as stream:
            stream.write(f"\nCheckpoint: **{manifest['size_status']}**, {compressed_bytes / MIB:.2f} MiB total; {len(parts)} parts. All rows retained. Prepared only; verify push receipt.\n")
    print(f"SAG30_CHECKPOINT_PREPARED bytes={compressed_bytes} parts={len(parts)} sha256={db_sha}")
    return manifest


def validate_manifest(manifest):
    if manifest.get('format') != FORMAT or not manifest.get('parts'):
        raise ValueError('Unsupported or empty checkpoint manifest')
    for index, part in enumerate(manifest['parts']):
        if part['name'] != f'radar.sqlite3.gz.part-{index:05d}' or not 0 < part['bytes'] < BLOB_LIMIT:
            raise ValueError('Invalid checkpoint part name, order or size')
        if not re.fullmatch('[a-f0-9]{64}', part['sha256']):
            raise ValueError('Invalid checkpoint checksum')
    if sum(p['bytes'] for p in manifest['parts']) != manifest['compressed_bytes']:
        raise ValueError('Checkpoint part sizes do not match manifest')
    names = set()
    for journal in manifest.get('journals', []):
        if journal['name'] not in JOURNALS or journal['name'] in names or journal['bytes'] < 0 or not re.fullmatch('[a-f0-9]{64}',journal['sha256']):
            raise ValueError('Invalid journal manifest')
        names.add(journal['name'])


def git_blob(repo, ref, name, destination):
    # Resolve a commit once in restore_git; never allow filenames/references as options.
    with Path(destination).open('wb') as stream:
        subprocess.run(['git', '-C', str(repo), 'show', f'{ref}:{name}'], stdout=stream, check=True)


def git_exists(repo, ref, name):
    return subprocess.run(['git','-C',str(repo),'cat-file','-e',f'{ref}:{name}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def restore_directory(directory, destination):
    directory, destination = Path(directory), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if any(Path(str(destination) + suffix).exists() for suffix in ('-wal','-shm')):
        raise ValueError('Refusing restore over a database with WAL/SHM sidecars')
    with tempfile.TemporaryDirectory(prefix='sag30-restore-', dir=destination.parent) as temp:
        temp = Path(temp)
        manifest_path = directory / MANIFEST
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            validate_manifest(manifest)
            compressed = temp / 'checkpoint.gz'
            digest = hashlib.sha256()
            with compressed.open('wb') as target:
                for part in manifest['parts']:
                    path = directory / part['name']
                    if path.stat().st_size != part['bytes'] or file_sha(path) != part['sha256']:
                        raise ValueError('Checkpoint part checksum/size mismatch: ' + part['name'])
                    with path.open('rb') as src:
                        for block in iter(lambda: src.read(MIB), b''):
                            target.write(block)
                            digest.update(block)
            if digest.hexdigest() != manifest['compressed_sha256']:
                raise ValueError('Compressed checkpoint checksum mismatch')
        elif (directory / 'radar.sqlite3.gz').is_file():
            compressed, manifest = directory / 'radar.sqlite3.gz', None
        elif (directory / 'radar.sqlite3').is_file():
            compressed, manifest = None, None
        else:
            raise ValueError('Checkpoint database missing; refusing empty recovery')
        restored = temp / 'restored.sqlite3'
        if compressed:
            with gzip.open(compressed, 'rb') as src, restored.open('wb') as dst:
                shutil.copyfileobj(src, dst, length=MIB)
        else:
            shutil.copyfile(directory / 'radar.sqlite3', restored)
        if manifest and (restored.stat().st_size != manifest['database_bytes'] or file_sha(restored) != manifest['database_sha256']):
            raise ValueError('Restored database checksum/size mismatch')
        counts = check_db(restored)
        if manifest and counts != manifest['table_counts']:
            raise ValueError('Restored audit row counts do not match manifest')
        # Failure leaves any existing destination intact. No partial checkpoint escapes.
        os.replace(restored, destination)
    print(f'SAG30_CHECKPOINT_RESTORE_PASS tables={len(counts)} rows={sum(counts.values())}')
    return counts


def restore_git(repo, ref, destination):
    commit = subprocess.check_output(['git','-C',str(repo),'rev-parse','--verify',ref+'^{commit}'], text=True).strip()
    with tempfile.TemporaryDirectory(prefix='sag30-git-checkpoint-') as directory:
        root = Path(directory)
        if git_exists(repo, commit, MANIFEST):
            git_blob(repo, commit, MANIFEST, root / MANIFEST)
            manifest = json.loads((root / MANIFEST).read_text())
            validate_manifest(manifest)
            for part in manifest['parts']:
                git_blob(repo, commit, part['name'], root / part['name'])
        else:
            for name in ('radar.sqlite3.gz', 'radar.sqlite3'):
                if git_exists(repo, commit, name):
                    git_blob(repo, commit, name, root / name)
                    break
            else:
                raise ValueError('State branch contains no durable checkpoint')
        return restore_directory(root, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--db', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--health')
    p.add_argument('--journals')
    p.add_argument('--base-commit')
    p.add_argument('--run-id')
    p = commands.add_parser('restore')
    p.add_argument('--repo', default='.')
    p.add_argument('--ref', default='FETCH_HEAD')
    p.add_argument('--directory', help='Restore a downloaded recovery artifact instead of Git')
    p.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.db,args.out,args.health,args.base_commit,args.run_id,journal_dir=args.journals)
    elif args.directory:
        restore_directory(args.directory,args.out)
    else:
        restore_git(args.repo,args.ref,args.out)

if __name__ == '__main__':
    main()
