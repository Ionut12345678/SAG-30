"""Operational restart tests with synthetic clocks/APIs only; no live dispatch."""
import base64
import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from radar.cadence import observation_window
from radar.restart import (admission, inspect_remote, market_data_status,
                           main, inspect_cadence_dispatch, verify_required_recovery, RESTORE, RECOVERY, SCAN, ROUTE, PREPARE, PERSIST)

NOW = datetime(2026, 10, 13, 13, 30, tzinfo=timezone.utc)


def health(start=NOW):
    return {'generated_ts': start.isoformat(),
            'checkpoint': {'workflow_run_id': '10'},
            'latest_run': {'started': start.isoformat(), 'status': 'DISCOVERY_OK'},
            'observations': {'ok': 1, 'valid_source_latest_ts': start.isoformat()},
            'observation_window_active': False}


def completed(start=NOW - timedelta(minutes=5)):
    return {'id': 10, 'status': 'completed', 'steps': {
        RESTORE: {'conclusion': 'success'}, ROUTE: {'conclusion': 'success'},
        SCAN: {'conclusion': 'success', 'started_at': start.isoformat()},
        PREPARE: {'conclusion': 'success'}, PERSIST: {'conclusion': 'success'}}}


class WindowTests(unittest.TestCase):
    def test_half_open_session_and_weekends(self):
        for hour, minute, expected in [(3, 59, False), (4, 0, True),
                                      (19, 59, True), (20, 0, False)]:
            local = datetime(2026, 10, 13, hour, minute, tzinfo=ZoneInfo('America/New_York'))
            self.assertEqual(observation_window(local), expected)
        self.assertFalse(observation_window(datetime(2026, 10, 17, 16, tzinfo=timezone.utc)))

    def test_us_dst_start_and_end_kickoff(self):
        for day, hour in [('2026-03-06', 9), ('2026-03-09', 8),
                          ('2026-10-30', 8), ('2026-11-02', 9)]:
            start = datetime.fromisoformat(day).replace(hour=hour, tzinfo=timezone.utc)
            self.assertFalse(observation_window(start - timedelta(seconds=1)))
            self.assertTrue(observation_window(start))

    def test_ro_and_us_dst_mismatch_uses_new_york(self):
        for date, ro_hour in [('2026-03-16', 10), ('2026-03-30', 11),
                             ('2026-10-26', 10), ('2026-11-02', 11)]:
            kickoff = datetime.fromisoformat(date).replace(hour=4, tzinfo=ZoneInfo('America/New_York'))
            self.assertEqual(kickoff.astimezone(ZoneInfo('Europe/Bucharest')).hour, ro_hour)
            self.assertTrue(observation_window(kickoff))

    def test_overnight_end_in_utc_and_naive_clock(self):
        self.assertFalse(observation_window(datetime(2026, 10, 13, 0, tzinfo=timezone.utc)))
        self.assertTrue(observation_window(datetime(2026, 11, 3, 0, 59, tzinfo=timezone.utc)))
        self.assertFalse(observation_window(datetime(2026, 11, 3, 1, tzinfo=timezone.utc)))
        with self.assertRaises(ValueError): observation_window(NOW.replace(tzinfo=None))


class AdmissionTests(unittest.TestCase):
    def test_initial_kickoff_and_long_interruption(self):
        self.assertTrue(admission(NOW, health(), [], 20)['allowed'])
        result = admission(NOW, health(), [completed(NOW - timedelta(hours=12))], 20)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['reason'], 'MISSING_CADENCE_EXECUTION')

    def test_not_due_then_due_without_overlapping(self):
        previous = completed(NOW - timedelta(seconds=299))
        self.assertFalse(admission(NOW, health(), [previous], 20)['allowed'])
        self.assertTrue(admission(NOW + timedelta(seconds=1), health(), [previous], 20)['allowed'])

    def test_session_end_never_restarts_from_old_health_flag(self):
        after = datetime(2026, 10, 14, 0, tzinfo=timezone.utc)
        stored = health(); stored['observation_window_active'] = True
        self.assertEqual(admission(after, stored, [completed()], 20)['status'], 'OUTSIDE_WINDOW')

    def test_running_peer_blocks_but_queued_successor_does_not(self):
        peer = {'id': 21, 'status': 'in_progress'}
        self.assertEqual(admission(NOW, health(), [peer, completed()], 20)['reason'], 'OTHER_RADAR_RUNNING')
        peer['status'] = 'queued'
        self.assertTrue(admission(NOW, health(), [peer, completed()], 20)['allowed'])
        self.assertTrue(admission(NOW, health(), [{'id': 20, 'status': 'in_progress'}, completed()], 20)['allowed'])

    def test_failed_preparation_and_unrecoverable_cancellation_block(self):
        for stage in (PREPARE, PERSIST):
            previous = completed(); previous['steps'][PERSIST]['conclusion'] = 'skipped'
            previous['steps'][stage]['conclusion'] = 'failure'
            result = admission(NOW, health(), [previous], 20)
            self.assertFalse(result['allowed'])
            self.assertEqual(result['reason'], 'UNPUBLISHED_CYCLE_WITHOUT_RECOVERY')

    def test_verified_recovery_is_required_before_further_scanning(self):
        previous = completed(); previous['steps'][PERSIST]['conclusion'] = 'failure'
        previous['recovery_artifact_available'] = True
        result = admission(NOW, health(), [previous], 20)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['reason'], 'RECOVERY_REQUIRED')
        self.assertEqual(result['checkpoint_verification'], 'REQUIRED_BEFORE_COLLECTION')
        self.assertEqual(result['required_recovery_run_id'], '10')

    def test_wrong_or_missing_recovery_cannot_lose_unpublished_cycle(self):
        for status in ({'status': 'NO_COMPATIBLE_RECOVERY_ARTIFACT'},
                       {'status': 'RESTORED_RECOVERY_ARTIFACT', 'workflow_run_id': 9}):
            with self.assertRaisesRegex(ValueError, 'not recovered'):
                verify_required_recovery(status, '10')
        verify_required_recovery({'status': 'RESTORED_RECOVERY_ARTIFACT', 'workflow_run_id': 10}, '10')
        verify_required_recovery({'status': 'NO_COMPATIBLE_RECOVERY_ARTIFACT'}, '')

    def test_restore_failure_and_state_mismatch_block(self):
        previous = completed(); previous['steps'][RESTORE]['conclusion'] = 'failure'
        self.assertEqual(admission(NOW, health(), [previous], 20)['reason'], 'PREVIOUS_RESTORE_UNVERIFIED')
        stored = health(); stored['checkpoint']['workflow_run_id'] = 9
        self.assertEqual(admission(NOW, stored, [completed()], 20)['reason'], 'PUBLISHED_STATE_RUN_MISMATCH')

    def test_failed_recovery_cannot_restart_collection(self):
        previous = completed()
        previous['steps'][RECOVERY] = {'conclusion': 'failure'}
        self.assertEqual(admission(NOW, health(), [previous], 20)['reason'], 'PREVIOUS_RECOVERY_UNVERIFIED')

    def test_missing_or_future_metadata_is_never_guessed(self):
        self.assertEqual(admission(NOW, {}, [], 20)['status'], 'BLOCKED')
        stored = health(NOW + timedelta(seconds=1))
        self.assertEqual(admission(NOW, stored, [], 20)['reason'], 'FUTURE_HEARTBEAT')
        stored['generated_ts'] = 'invalid'
        self.assertEqual(admission(NOW, stored, [], 20)['reason'], 'INVALID_HEARTBEAT_TIMESTAMP')

    def test_data_gap_is_explicit_but_not_a_reason_to_stop_safe_collection(self):
        stored = health(); stored['observations']['ok'] = 0
        result = admission(NOW, stored, [completed()], 20)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['market_data_status'], 'DATA_GAP')
        self.assertFalse(result['buy'])

    def test_http_freshness_does_not_refresh_provider_timestamp(self):
        stored = health()
        stored['observations']['valid_source_latest_ts'] = (NOW - timedelta(seconds=901)).isoformat()
        self.assertEqual(market_data_status(stored, NOW), 'DATA_GAP')
        stored['observations']['valid_source_latest_ts'] = (NOW + timedelta(seconds=1)).isoformat()
        self.assertEqual(market_data_status(stored, NOW), 'DATA_GAP')
        self.assertEqual(market_data_status(health(), NOW), 'VALID_OBSERVATIONS_SHADOW_ONLY')

    def test_input_is_read_only(self):
        stored, runs = health(), [completed()]
        before = copy.deepcopy((stored, runs))
        admission(NOW, stored, runs, 20)
        self.assertEqual((stored, runs), before)


class RemoteAndCliTests(unittest.TestCase):
    def test_live_early_dispatch_waits_then_continues_chain(self):
        # Run #559 arrived at 272.928601 seconds and previously killed the chain.
        previous = completed(NOW - timedelta(seconds=272.928601))
        later = NOW + timedelta(seconds=28)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return later
        def inspect(repo, current_id, now, target):
            return admission(now, health(NOW), [previous], current_id, target)
        with patch('radar.restart.inspect_remote', side_effect=inspect) as remote, \
             patch('radar.restart.time.sleep') as sleep, patch('radar.restart.datetime', Clock):
            result = inspect_cadence_dispatch('owner/repo', 20, NOW)
        sleep.assert_called_once_with(28)
        self.assertEqual(remote.call_count, 2)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['reason'], 'CADENCE_DUE')
        self.assertGreaterEqual(result['elapsed_seconds'], 300)

    def test_early_dispatch_rechecks_close_checkpoint_and_peer_after_wait(self):
        initial = admission(NOW, health(), [completed(NOW - timedelta(seconds=270))], 20)
        cases = [
            admission(datetime(2026, 10, 14, 0, tzinfo=timezone.utc), health(), [], 20),
            admission(NOW, {}, [], 20),
            admission(NOW, health(), [{'id': 21, 'status': 'in_progress'}], 20),
        ]
        for refreshed in cases:
            with self.subTest(reason=refreshed['reason']), \
                 patch('radar.restart.inspect_remote', side_effect=[initial, refreshed]), \
                 patch('radar.restart.time.sleep'):
                result = inspect_cadence_dispatch('owner/repo', 20, NOW)
            self.assertFalse(result['allowed'])
            self.assertEqual(result['reason'], refreshed['reason'])

    def test_wait_is_bounded_and_never_releases_a_still_recent_cycle(self):
        for elapsed, expected in [(1, 'CADENCE_WAIT_OUT_OF_BOUNDS'),
                                  (270, 'CADENCE_CHANGED_DURING_WAIT')]:
            initial = admission(NOW, health(), [completed(NOW - timedelta(seconds=elapsed))], 20)
            with patch('radar.restart.inspect_remote', return_value=initial), \
                 patch('radar.restart.time.sleep') as sleep:
                result = inspect_cadence_dispatch('owner/repo', 20, NOW)
            self.assertFalse(result['allowed'])
            self.assertEqual(result['reason'], expected)
            self.assertEqual(sleep.call_count, int(elapsed == 270))

    def test_due_or_blocked_dispatch_does_not_wait(self):
        for initial in [admission(NOW, health(), [completed()], 20),
                        admission(NOW, {}, [], 20)]:
            with patch('radar.restart.inspect_remote', return_value=initial), \
                 patch('radar.restart.time.sleep') as sleep:
                self.assertEqual(inspect_cadence_dispatch('owner/repo', 20, NOW), initial)
            sleep.assert_not_called()

    def test_health_carries_only_valid_provider_source_timestamp(self):
        from radar.core import open_db, record
        from radar.health import build
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'radar.sqlite3'
            db = open_db(path)
            db.execute('INSERT INTO runs(id,started,finished,status) VALUES(1,?,?,?)',
                       (NOW.isoformat(), NOW.isoformat(), 'MONITOR_OK'))
            record(db, 1, 'TEST', {'latestTrade': {'p': 10.5, 't': NOW.isoformat()},
                                 'prevDailyBar': {'c': 10, 't': '2026-10-12T20:00:00Z'}},
                   NOW.isoformat(), NOW.isoformat(), 900)
            record(db, 1, 'STALE', {'latestTrade': {'p': 10.5, 't': (NOW - timedelta(hours=1)).isoformat()},
                                  'prevDailyBar': {'c': 10, 't': '2026-10-12T20:00:00Z'}},
                   NOW.isoformat(), NOW.isoformat(), 900)
            db.commit(); db.close()
            result = build(path, now=NOW)
            self.assertEqual(result['observations']['ok'], 1)
            self.assertEqual(result['observations']['valid_source_latest_ts'], NOW.isoformat())
            self.assertEqual(market_data_status(result, NOW), 'VALID_OBSERVATIONS_SHADOW_ONLY')
            self.assertEqual(market_data_status(result, NOW + timedelta(seconds=901)), 'DATA_GAP')

    def test_watchdog_warning_fails_active_run_but_preserves_report(self):
        from radar.free_watchdog import main as watchdog_main
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return NOW if tz else NOW.replace(tzinfo=None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'health.json').write_text(json.dumps(health(NOW - timedelta(hours=12))))
            with patch('radar.free_watchdog.datetime', Clock), patch('sys.argv', [
                'watchdog', '--health', str(root / 'health.json'),
                '--output', str(root / 'result.json'), '--fail-on-active-warning']):
                self.assertEqual(watchdog_main(), 1)
            self.assertIn('STALE_HEARTBEAT', json.loads((root / 'result.json').read_text())['reasons'])

    def test_remote_walks_skipped_admissions_and_recovers_cadence(self):
        previous = completed(NOW - timedelta(hours=12))
        runs = [{'id': i, 'head_branch': 'main', 'path': '.github/workflows/radar.yml',
                 'status': 'completed'} for i in (19, 10)]
        def api(path):
            if '/contents/' in path:
                return {'content': base64.b64encode(json.dumps(health()).encode()).decode()}
            if '/workflows/' in path: return {'workflow_runs': runs}
            if '/19/jobs' in path: return {'jobs': [{'name': 'observe', 'conclusion': 'skipped', 'steps': []}]}
            return {'jobs': [{'name': 'observe', 'conclusion': 'success',
                             'steps': [dict(v, name=k) for k, v in previous['steps'].items()]}]}
        with patch('radar.restart.gh_json', side_effect=api):
            result = inspect_remote('owner/repo', 20, NOW)
        self.assertEqual(result['reason'], 'MISSING_CADENCE_EXECUTION')
        self.assertTrue(result['allowed'])

    def test_off_hours_never_requests_state_or_provider(self):
        with patch('radar.restart.gh_json', side_effect=AssertionError('unexpected API')):
            self.assertFalse(inspect_remote('owner/repo', 20, datetime(2026, 10, 14, 0, tzinfo=timezone.utc))['allowed'])

    def test_api_failure_writes_blocked_evidence_and_fails_ci_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            with patch('sys.argv', ['restart', '--repo', 'owner/repo', '--output', str(output)]), \
                 patch('radar.restart.inspect_remote', side_effect=subprocess.CalledProcessError(1, 'gh')):
                self.assertEqual(main(), 1)
            self.assertEqual(json.loads(output.read_text())['reason'], 'ADMISSION_INPUT_OR_API_UNAVAILABLE')

    def test_workflow_preserves_lock_restore_recovery_and_no_branch_production(self):
        workflow = Path('.github/workflows/radar.yml').read_text()
        self.assertIn('group: sag30-state\n  cancel-in-progress: false', workflow)
        self.assertIn("needs.admission.outputs.allowed == 'true'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("always() && !cancelled() && steps.persist.outcome == 'success'", workflow)
        self.assertIn('--force-with-lease="radar-state:$expected"', workflow)
        recovery = workflow.split('      - name: Recover unpublished prospective cycle before scanning\n', 1)[1].split('\n      - name:', 1)[0]
        self.assertIn('verify_required_recovery', recovery)
        self.assertIn('SAG30_CADENCE_WINDOW_ENDED_AFTER_WAIT', workflow)

    def test_real_dispatch_shell_does_not_dispatch_after_wait_crosses_close(self):
        workflow = Path('.github/workflows/radar.yml').read_text()
        block = workflow.split('      - name: Dispatch next cadence cycle\n', 1)[1].split('\n      - name:', 1)[0]
        script = '\n'.join(line[10:] for line in block.split('        run: |\n', 1)[1].splitlines() if line.startswith('          '))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Clock shim: window open, one-second wait, then window closed.
            (root / 'python').write_text('#!/bin/bash\nn=$(cat "$CLOCK_FILE" 2>/dev/null || echo 0)\nn=$((n+1)); echo "$n" > "$CLOCK_FILE"\ncase "$n" in 1|2) echo 1 ;; *) exit 1 ;; esac\n')
            (root / 'sleep').write_text('#!/bin/bash\nexit 0\n')
            (root / 'gh').write_text('#!/bin/bash\ntouch "$DISPATCH_MARKER"\nexit 0\n')
            for name in ('python', 'sleep', 'gh'): (root / name).chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       CLOCK_FILE=str(root / 'clock'), DISPATCH_MARKER=str(root / 'dispatched'))
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('SAG30_CADENCE_WINDOW_ENDED_AFTER_WAIT', result.stdout)
            self.assertFalse((root / 'dispatched').exists())


if __name__ == '__main__':
    unittest.main()
