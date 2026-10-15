"""Fail-closed operator-approved preparation of an explicitly missing cycle.

This is a READ-ONLY preflight, NOT an admission bypass or deployment action.
It cannot claim a failed cycle was recovered or that Gate 0 passed.
"""
import argparse
import json
import hashlib
import sqlite3
from pathlib import Path

INCIDENT_RUN = '38423433985'
PUBLISHED_RUN = '38422640857'
PUBLISHED_DB_SHA = '9107abf54ff554a4670576a5be678c2631fbc824591f5d99dc62fc3a9a1874a5'
DIAGNOSTIC_NAME = 'sag30-restart-diagnostic'
RECOVERY_NAME = 'sag30-checkpoint-recovery'



def verify_restored_checkpoint(db_path, manifest, journal_dir):
    """Fail closed on the actual restored bytes, not merely health metadata.

    This does not restore the missing cycle or authorize admission. Call only
    after radar.checkpoint.restore has verified the compressed parts.
    """
    errors = []
    db_path = Path(db_path)
    journal_dir = Path(journal_dir)
    if not db_path.is_file():
        return ['RESTORED_SQLITE_MISSING']
    digest = hashlib.sha256()
    with db_path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != PUBLISHED_DB_SHA or digest.hexdigest() != manifest.get('database_sha256'):
        errors.append('RESTORED_SQLITE_HASH_MISMATCH')
    if db_path.stat().st_size != manifest.get('database_bytes'):
        errors.append('RESTORED_SQLITE_SIZE_MISMATCH')
    try:
        uri = db_path.resolve().as_uri() + '?mode=ro&immutable=1'
        with sqlite3.connect(uri, uri=True) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                errors.append('RESTORED_SQLITE_INTEGRITY_FAILED')
            actual = {name: count for name, count in
                      ((name, db.execute('SELECT COUNT(*) FROM "' +
                        name.replace('"', '""') + '"').fetchone()[0])
                       for name in (manifest.get('table_counts') or {}))}
            if actual != manifest.get('table_counts'):
                errors.append('PUBLISHED_TABLE_COUNTS_MISMATCH')
    except (sqlite3.Error, OSError, ValueError):
        errors.append('RESTORED_SQLITE_INTEGRITY_FAILED')
    for journal in manifest.get('journals', []):
        name = journal.get('name', '')
        if name not in ('shadow_first_watch.jsonl',
                        'shadow_watch_observations.jsonl', 'shadow_watch_status.json'):
            errors.append('UNRECOGNIZED_PUBLISHED_JOURNAL')
            continue
        path = journal_dir / name
        if not path.is_file() or path.stat().st_size != journal.get('bytes'):
            errors.append('PUBLISHED_JOURNAL_MISSING_OR_SIZE_MISMATCH')
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != journal.get('sha256'):
            errors.append('PUBLISHED_JOURNAL_HASH_MISMATCH')
    if manifest.get('audit_retention') != 'ALL_ROWS_NO_PRUNING':
        errors.append('AUDIT_RETENTION_NOT_VERIFIED')
    return errors


def preflight(health, manifest, artifacts, *, operator_authorized=False):
    """Verify the exact historical parent and absent artifact; never mutate state."""
    errors = []
    checkpoint = health.get('checkpoint') or {}
    if str(checkpoint.get('workflow_run_id')) != PUBLISHED_RUN:
        errors.append('PUBLISHED_RUN_CHANGED')
    if checkpoint.get('database_sha256') != PUBLISHED_DB_SHA:
        errors.append('PUBLISHED_DB_HASH_CHANGED')
    if str(manifest.get('workflow_run_id')) != PUBLISHED_RUN:
        errors.append('MANIFEST_RUN_MISMATCH')
    if manifest.get('database_sha256') != PUBLISHED_DB_SHA:
        errors.append('MANIFEST_DB_HASH_MISMATCH')
    if manifest.get('audit_retention') != 'ALL_ROWS_NO_PRUNING':
        errors.append('AUDIT_RETENTION_NOT_VERIFIED')
    # The GitHub Actions REST response is an object with an "artifacts" list.
    # Accept that unmodified response as well as a deliberately extracted list.
    if isinstance(artifacts, dict):
        artifacts = artifacts.get('artifacts')
    if not isinstance(artifacts, list) or any(not isinstance(a, dict) for a in artifacts):
        errors.append('ARTIFACT_INVENTORY_MISSING')
        artifacts = []
    for item in artifacts:
        source_run = (item.get('workflow_run') or {}).get('id')
        if source_run is not None and str(source_run) != INCIDENT_RUN:
            errors.append('ARTIFACT_FROM_DIFFERENT_RUN')
    live = [item for item in artifacts if item.get('expired') is not True]
    names = [item.get('name') for item in live]
    if RECOVERY_NAME in [item.get('name') for item in artifacts]:
        errors.append('RECOVERY_ARTIFACT_EXISTS_USE_EXACT_RECOVERY')
    if DIAGNOSTIC_NAME not in names:
        errors.append('INCIDENT_DIAGNOSTIC_MISSING')
    if not operator_authorized:
        errors.append('OPERATOR_AUTHORIZATION_MISSING')
    return {
        'incident_workflow_run_id': INCIDENT_RUN,
        'last_published_workflow_run_id': PUBLISHED_RUN,
        'last_published_database_sha256': PUBLISHED_DB_SHA,
        'incident_status': 'UNKNOWN_NOT_RECOVERED',
        'data_gap': True,
        'first_seen_reconstruction': False,
        'gate0': 'BLOCKED',
        'buy': False,
        'preflight': 'PASS_PREPARATION_ONLY' if not errors else 'BLOCKED',
        'resume_executed': False,
        'errors': errors,
        'next_step': 'SEPARATE_REVIEWED_ONE_TIME_RESUME_IMPLEMENTATION_AND_LIVE_VERIFICATION'
                     if not errors else 'PRESERVE_STATE_AND_RESOLVE_ERRORS',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--health', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--incident-artifacts', type=Path, required=True)
    parser.add_argument('--operator-authorized', action='store_true')
    parser.add_argument('--restored-db', type=Path)
    parser.add_argument('--journal-dir', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    result = preflight(json.loads(args.health.read_text()),
                       manifest,
                       json.loads(args.incident_artifacts.read_text()),
                       operator_authorized=args.operator_authorized)
    if args.restored_db is None or args.journal_dir is None:
        result['errors'].append('LOCAL_CHECKPOINT_VERIFICATION_REQUIRED')
    elif not result['errors']:
        result['errors'].extend(verify_restored_checkpoint(args.restored_db, manifest, args.journal_dir))
    result['preflight'] = 'PASS_PREPARATION_ONLY' if not result['errors'] else 'BLOCKED'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['preflight'] == 'PASS_PREPARATION_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
