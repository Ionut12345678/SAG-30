"""Fail-closed operator-approved preparation of an explicitly missing cycle.

This is a READ-ONLY preflight, NOT an admission bypass or deployment action.
It cannot claim a failed cycle was recovered or that Gate 0 passed.
"""
import argparse
import json
from pathlib import Path

INCIDENT_RUN = '38423433985'
PUBLISHED_RUN = '38422640857'
PUBLISHED_DB_SHA = '9107abf54ff554a4670576a5be678c2631fbc824591f5d99dc62fc3a9a1874a5'
DIAGNOSTIC_NAME = 'sag30-restart-diagnostic'
RECOVERY_NAME = 'sag30-checkpoint-recovery'


def preflight(health, manifest, artifacts, *, operator_authorized=False, restore_evidence=None):
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
    if not isinstance(artifacts, list):
        errors.append('ARTIFACT_INVENTORY_MISSING')
        artifacts = []
    names = [item.get('name') for item in artifacts]
    if RECOVERY_NAME in names:
        errors.append('RECOVERY_ARTIFACT_EXISTS_USE_EXACT_RECOVERY')
    diagnostics = [item for item in artifacts if item.get('name') == DIAGNOSTIC_NAME]
    if len(diagnostics) != 1:
        errors.append('INCIDENT_DIAGNOSTIC_MISSING_OR_AMBIGUOUS')
    else:
        diagnostic = diagnostics[0]
        if str((diagnostic.get('workflow_run') or {}).get('id')) != INCIDENT_RUN:
            errors.append('INCIDENT_DIAGNOSTIC_RUN_UNVERIFIED')
        if diagnostic.get('expired') is not False:
            errors.append('INCIDENT_DIAGNOSTIC_AVAILABILITY_UNVERIFIED')
    # Metadata is not proof of a readable checkpoint; demand an independent
    # isolated restore receipt before allowing even preparation to pass.
    if not isinstance(restore_evidence, dict):
        errors.append('ISOLATED_RESTORE_EVIDENCE_MISSING')
    else:
        if restore_evidence.get('integrity_check') != 'ok':
            errors.append('ISOLATED_RESTORE_INTEGRITY_UNVERIFIED')
        if restore_evidence.get('audit_journals_preserved') is not True:
            errors.append('ISOLATED_RESTORE_JOURNALS_UNVERIFIED')
        if restore_evidence.get('database_sha256') != PUBLISHED_DB_SHA:
            errors.append('ISOLATED_RESTORE_HASH_MISMATCH')
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
    parser.add_argument('--restore-evidence', type=Path, required=True,
                        help='Independent isolated restore receipt; no remote writes')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = preflight(json.loads(args.health.read_text()),
                       json.loads(args.manifest.read_text()),
                       json.loads(args.incident_artifacts.read_text()),
                       operator_authorized=args.operator_authorized,
                       restore_evidence=json.loads(args.restore_evidence.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['preflight'] == 'PASS_PREPARATION_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
