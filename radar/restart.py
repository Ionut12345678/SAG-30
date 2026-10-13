"""Read-only admission and evidence diagnostics; never dispatches or edits state.

Admission runs under the workflow's sag30-state concurrency lock. Collection
still requires the existing checksum/SQLite/journal restore and recovery gates.
"""
import argparse
import base64
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from .cadence import observation_window

RESTORE = 'Restore durable state'
RECOVERY = 'Recover unpublished prospective cycle before scanning'
SCAN = 'Observe one prospective cycle'
ROUTE = 'Run v0.4.12 EARLY-PREMARKET ROUTING SHADOW'
PREPARE = 'Prepare lossless bounded checkpoint and size alerts'
PERSIST = 'Persist audit state and heartbeat'


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    return parsed.astimezone(timezone.utc)


def market_data_status(health, now, max_source_age=900):
    """Re-evaluate age now, never trust the stored observation-window flag."""
    if not observation_window(now):
        return 'OUTSIDE_WINDOW'
    if not isinstance(health, dict):
        return 'DATA_GAP'
    try:
        run = health.get('latest_run') or {}
        age = (now - stamp(run['started'])).total_seconds()
        heartbeat_age = (now - stamp(health['generated_ts'])).total_seconds()
        source_age = (now - stamp(health['observations']['valid_source_latest_ts'])).total_seconds()
        if not 0 <= age <= 900 or not 0 <= heartbeat_age <= 900:
            return 'DATA_GAP'
        if not 0 <= source_age <= max_source_age:
            return 'DATA_GAP'
    except (KeyError, ValueError, TypeError, AttributeError):
        return 'DATA_GAP'
    if (health.get('observations') or {}).get('ok', 0) <= 0:
        return 'DATA_GAP'
    if run.get('status') in ('FAILED', 'MONITOR_DATA_GAP'):
        return 'DATA_GAP'
    # OK counts use existing quality gates, and source freshness is rechecked now.
    return 'VALID_OBSERVATIONS_SHADOW_ONLY'


def admission(now, health, runs, current_id, target=300):
    if target <= 0:
        raise ValueError('positive cadence target required')
    result = {'generated_ts': now.isoformat(), 'allowed': False,
              'status': 'OUTSIDE_WINDOW', 'reason': 'OUTSIDE_WINDOW',
              'market_data_status': market_data_status(health, now),
              'checkpoint_verification': 'REQUIRED_BEFORE_COLLECTION',
              'buy': False}
    if not observation_window(now):
        return result
    def decide(status, reason, allowed=False):
        result.update(status=status, reason=reason, allowed=allowed)
        return result
    peers = [r for r in runs if str(r['id']) != str(current_id)]
    if any(r['status'] == 'in_progress' for r in peers):
        return decide('BLOCKED', 'OTHER_RADAR_RUNNING')
    if not isinstance(health, dict) or not isinstance(health.get('checkpoint'), dict):
        return decide('BLOCKED', 'PUBLISHED_CHECKPOINT_METADATA_MISSING')
    try:
        if stamp(health['generated_ts']) > now:
            return decide('BLOCKED', 'FUTURE_HEARTBEAT')
    except (KeyError, ValueError, TypeError, AttributeError):
        return decide('BLOCKED', 'INVALID_HEARTBEAT_TIMESTAMP')
    previous = next((r for r in peers if r.get('steps')), None)
    if previous:
        result['previous_run_id'] = previous['id']
        steps = previous['steps']
        if steps.get(RESTORE, {}).get('conclusion') != 'success':
            return decide('BLOCKED', 'PREVIOUS_RESTORE_UNVERIFIED')
        if steps.get(RECOVERY, {}).get('conclusion') in ('failure', 'cancelled'):
            return decide('BLOCKED', 'PREVIOUS_RECOVERY_UNVERIFIED')
        published = steps.get(PERSIST, {}).get('conclusion') == 'success'
        processing = any(steps.get(name, {}).get('conclusion') != 'skipped'
                         and name in steps for name in (ROUTE, SCAN))
        if processing and not published:
            if (steps.get(PREPARE, {}).get('conclusion') != 'success'
                    or not previous.get('recovery_artifact_available')):
                return decide('BLOCKED', 'UNPUBLISHED_CYCLE_WITHOUT_RECOVERY')
            # Metadata allows only entry into restore/recovery, never scanning directly.
            return decide('DUE', 'RECOVERY_REQUIRED', True)
        if published:
            if str(health['checkpoint'].get('workflow_run_id')) != str(previous['id']):
                return decide('BLOCKED', 'PUBLISHED_STATE_RUN_MISMATCH')
            try:
                started = stamp(steps[SCAN]['started_at'])
                elapsed = (now - started).total_seconds()
            except (KeyError, ValueError, TypeError, AttributeError):
                return decide('BLOCKED', 'PREVIOUS_CYCLE_TIMESTAMP_INVALID')
            result['elapsed_seconds'] = elapsed
            if elapsed < 0:
                return decide('BLOCKED', 'FUTURE_CYCLE')
            if elapsed < target:
                return decide('NOT_DUE', 'RECENT_PUBLISHED_CYCLE')
            reason = 'MISSING_CADENCE_EXECUTION' if elapsed > 2 * target else 'CADENCE_DUE'
            return decide('DUE', reason, True)
    return decide('DUE', 'SESSION_START_OR_NO_RECENT_RUN', True)


def gh_json(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def inspect_remote(repo, current_id, now, target=300):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid repository identity')
    # Off-hours scheduled jobs are cheap and cannot touch the checkpoint.
    if not observation_window(now):
        return admission(now, None, [], current_id, target)
    raw = gh_json(f'repos/{repo}/contents/health.json?ref=radar-state')
    health = json.loads(base64.b64decode(raw['content']))
    runs, page = [], 1
    while True:
        items = gh_json(f'repos/{repo}/actions/workflows/radar.yml/runs?per_page=100&page={page}')['workflow_runs']
        runs.extend(r for r in items if r['head_branch'] == 'main'
                    and r['path'] == '.github/workflows/radar.yml'
                    and str(r['id']) != str(current_id))
        found = False
        for run in runs:
            if run['status'] != 'completed' or 'steps' in run:
                continue
            jobs = gh_json(f'repos/{repo}/actions/runs/{run["id"]}/jobs?filter=latest&per_page=100')['jobs']
            job = next((j for j in jobs if j['name'] == 'observe' and j['conclusion'] != 'skipped'), None)
            run['steps'] = {s['name']: s for s in job['steps']} if job else {}
            if run['steps']:
                found = True
                if run['steps'].get(PERSIST, {}).get('conclusion') != 'success':
                    artifacts = gh_json(f'repos/{repo}/actions/runs/{run["id"]}/artifacts?per_page=100')['artifacts']
                    run['recovery_artifact_available'] = any(
                        a['name'] == 'sag30-checkpoint-recovery' and not a['expired'] for a in artifacts)
                break
        if found or len(items) < 100:
            break
        page += 1
        if page > 10:
            raise ValueError('Recent radar collection history unavailable; refusing to guess')
    # API ordering is newest first; queued successors are not unsafe running peers.
    return admission(now, health, runs, current_id, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo')
    parser.add_argument('--run-id', default=os.getenv('GITHUB_RUN_ID'))
    parser.add_argument('--config', default='config/radar.json')
    parser.add_argument('--health', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        if args.health:
            health = json.loads(args.health.read_text())
            config = json.loads(Path(args.config).read_text())
            result = {'technical_status': 'COMPLETED',
                      'market_data_status': market_data_status(health, now, config.get('max_source_age_seconds', 900)), 'buy': False}
        else:
            target = int(json.loads(Path(args.config).read_text()).get('cadence_target_seconds', 300))
            result = inspect_remote(args.repo, args.run_id, now, target)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError):
        result = {'allowed': False, 'status': 'BLOCKED',
                  'reason': 'ADMISSION_INPUT_OR_API_UNAVAILABLE', 'buy': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, sort_keys=True) + '\n'
    args.output.write_text(payload)
    print(payload)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('\nSAG-30 operational result (SHADOW / NOT BUY):\n```json\n' + payload + '```\n')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as outputs:
            outputs.write('allowed=' + str(result.get('allowed', False)).lower() + '\n')
    if result.get('market_data_status') == 'DATA_GAP':
        print('::warning::SAG30_DATA_GAP: technical completion is not valid market evidence')
    if result.get('reason') == 'MISSING_CADENCE_EXECUTION':
        print('::warning::SAG30_MISSING_CADENCE_EXECUTION: attempting verified recovery/start')
    if result.get('status') == 'BLOCKED':
        print('::error::SAG30_RESTART_BLOCKED: ' + result['reason'])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
