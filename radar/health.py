"""Machine-readable operational heartbeat for SAG-30 infrastructure.

This reports what the collector actually did. It does not infer or modify frozen model gates.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .model import SPEC_SHA256

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def _source_at_or_after(source_ts, transition):
    """True only when a timezone-aware provider trade is on/after cutoff."""
    try:
        source_dt = datetime.fromisoformat(source_ts.replace('Z', '+00:00'))
        cutoff_dt = datetime.fromisoformat(transition)
        return bool(source_dt.tzinfo and cutoff_dt.tzinfo and source_dt >= cutoff_dt)
    except (TypeError, ValueError, AttributeError):
        return False

def _table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

def build(db_path, scan_rc=0, bridge_rc=0, fast_path_outcome=None, cadence_target_seconds=300, now=None, fast_path_mode='UNKNOWN'):
    now = now or datetime.now(timezone.utc)
    result = {
        'generated_ts': now.isoformat(),
        'frozen_version': 'SAG-30 Early Radar v0.3.3 FROZEN SHADOW',
        'spec_sha256': SPEC_SHA256,
        'workflow': {'scan_rc': int(scan_rc), 'bridge_rc': int(bridge_rc)},
        'health': 'FAIL' if int(scan_rc) else ('DEGRADED' if int(bridge_rc) else 'PASS'),
        'reason_codes': [],
        'latest_run': None,
        'observations': {'total': 0, 'ok': 0, 'data_quality': 0},
        'evaluation_states': {},
        'candidate_count': 0,
        'pending_bridge_events': 0,
        'last_signal': None,
        'cadence_gap_seconds': None,
        'model_readiness': {'status': 'NO_OBSERVATIONS', 'activity_confirmable_packets': 0},
        'semantic_shadow': {'packets': 0, 'with_history_samples': 0, 'with_observed_volume_ratio': 0, 'new_observed_highs': 0, 'two_positive_intervals': 0},
        'candidate_v034': {'status':'NO_DATA','states':{},'lanes':{},'signals_total':0,'last_signal':None},
        'candidate_v034r2': {'status':'NO_DATA','states':{},'signals_total':0,'last_signal':None},
        'fast_scout': {'status':'NO_DATA'},
        'fast_path': {'status':('FAIL' if fast_path_outcome in ('failure','cancelled') else 'NOT_RUN' if fast_path_outcome == 'skipped' else 'NO_DATA'), 'workflow_outcome':fast_path_outcome, 'mode':fast_path_mode},
        'cadence': {'target_seconds':cadence_target_seconds, 'status':'NO_PREVIOUS_RUN'},
    }
    current_et=now.astimezone(ZoneInfo('America/New_York'))
    observation_window=current_et.weekday()<5 and 4<=current_et.hour<20
    result['observation_window_active']=observation_window
    result['checkpoint_is_current_cycle']=False
    path = Path(db_path)
    if not path.exists():
        result['health'] = 'FAIL'
        result['detail'] = 'audit database missing'
        result['reason_codes'] = ['AUDIT_DATABASE_MISSING']
        return result
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        latest = db.execute('SELECT id,started,finished,status,detail FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        if latest:
            run_id, started, finished, status, detail = latest
            result['latest_run'] = {'id': run_id, 'started': started, 'finished': finished, 'status': status, 'detail': detail}
            # A successful off-hours workflow may legitimately contain an old run.
            # Never present that persisted run as current-cycle evidence.
            result['checkpoint_is_current_cycle'] = (
                datetime.fromisoformat(started).astimezone(ZoneInfo('America/New_York')).date()==current_et.date()
                and 0 <= (now-datetime.fromisoformat(started)).total_seconds() <= 900
            )
            total, ok = db.execute("SELECT COUNT(*),SUM(CASE WHEN quality='OK' THEN 1 ELSE 0 END) FROM observations WHERE run_id=?", (run_id,)).fetchone()
            total, ok = int(total or 0), int(ok or 0)
            result['observations'] = {'total': total, 'ok': ok, 'data_quality': total-ok}
            # Audit the stored prospective rejection reasons without reclassifying observations.
            # One observation may carry multiple reasons; counts are not exclusive.
            reason_counts = {}
            for (reason,) in db.execute("SELECT reason FROM observations WHERE run_id=? AND quality!='OK'", (run_id,)):
                for code in (reason or 'unspecified').split(','):
                    code = code.strip() or 'unspecified'
                    reason_counts[code] = reason_counts.get(code, 0) + 1
            result['observations']['rejection_reasons'] = dict(sorted(reason_counts.items()))

            # Prospective age diagnostics, never a substitute for quality='OK'.
            # Age is measured from the provider's trade timestamp, not the HTTP response.
            age_bins = {'future': 0, '0_60s': 0, '60_300s': 0,
                        '300_900s': 0, 'over_900s': 0, 'missing_or_invalid': 0}
            for retrieval_ts, source_ts in db.execute(
                'SELECT retrieval_ts,source_ts FROM observations WHERE run_id=?', (run_id,)
            ):
                try:
                    retrieved_dt = datetime.fromisoformat(retrieval_ts)
                    source_dt = datetime.fromisoformat(source_ts.replace('Z', '+00:00'))
                    if retrieved_dt.tzinfo is None or source_dt.tzinfo is None:
                        raise ValueError('timezone missing')
                    age = (retrieved_dt-source_dt).total_seconds()
                    bucket = ('future' if age < 0 else '0_60s' if age <= 60
                              else '60_300s' if age <= 300 else '300_900s'
                              if age <= 900 else 'over_900s')
                except (TypeError, ValueError, AttributeError):
                    bucket = 'missing_or_invalid'
                age_bins[bucket] += 1
            result['observations']['source_trade_age_bins'] = age_bins
            from .freshness import quote_diagnostic
            quote_counts = {}
            for payload, retrieved in db.execute('SELECT payload,retrieval_ts FROM observations WHERE run_id=?', (run_id,)):
                diagnostic = quote_diagnostic(json.loads(payload), retrieved)
                code = diagnostic['reason'] or diagnostic['status']
                quote_counts[code] = quote_counts.get(code, 0) + 1
            result['execution_diagnostics'] = {'quote_counts': quote_counts,
                'quote_max_age_seconds': 300, 'halt_status': 'UNKNOWN',
                'execution_actionable': 'UNKNOWN', 'authoritative': False,
                'provider_fallback': 'NOT_INFERRED_FROM_SHADOW_ROUTING'}

            # Link only routes observed during this same prospective run to later
            # observations. Never use pre-route snapshots as downstream evidence.
            if _table_exists(db, 'v0412_premarket_route'):
                routed = db.execute(
                    """SELECT symbol, observed_ts FROM v0412_premarket_route
                       WHERE session=? AND status='EARLY_PREMARKET_ROUTE_SHADOW'
                         AND observed_ts>=? AND observed_ts<=?""",
                    (current_et.date().isoformat(), (datetime.fromisoformat(started)-timedelta(minutes=5)).isoformat(), min(datetime.fromisoformat(finished), now).isoformat() if finished else now.isoformat()),
                ).fetchall()
                valid = 0
                any_observation = 0
                for symbol, route_ts in routed:
                    match = db.execute(
                        """SELECT COUNT(*), SUM(CASE WHEN quality='OK' THEN 1 ELSE 0 END)
                           FROM observations WHERE run_id=? AND symbol=?
                           AND retrieval_ts>=?""",
                        (run_id, symbol, route_ts),
                    ).fetchone()
                    any_observation += int((match or (0, 0))[0] or 0) > 0
                    valid += int((match or (0, 0))[1] or 0) > 0
                result['v0412_downstream'] = {
                    'status': 'SHADOW_NOT_MODEL_EVIDENCE',
                    'same_run_routes': len(routed),
                    'with_post_route_observation': any_observation,
                    'with_valid_post_route_observation': valid,
                    'without_valid_post_route_observation': len(routed)-valid,
                    'note': 'Only same-run post-route snapshots; no historical backfill or BUY',
                }
                # Session-long prospective cohort: earliest premarket route per
                # symbol, followed only by later observations on the same day.
                # Keep cross-run evidence audit separate from frozen evaluation.
                cohort = db.execute(
                    """SELECT symbol,MIN(observed_ts) FROM v0412_premarket_route
                       WHERE session=? AND status='EARLY_PREMARKET_ROUTE_SHADOW'
                       GROUP BY symbol""", (current_et.date().isoformat(),)
                ).fetchall()
                session_iex = {'routed_symbols': len(cohort),
                               'observed_after_route': 0,
                               'valid_after_route': 0,
                               'valid_after_08_et': 0,
                               'valid_source_after_08_et': 0,
                               'converted_symbols': []}
                transition = current_et.replace(
                    hour=8,minute=0,second=0,microsecond=0
                ).astimezone(timezone.utc).isoformat()
                for symbol, first_route in cohort:
                    counts = db.execute(
                        """SELECT COUNT(*),
                                  SUM(CASE WHEN quality='OK' THEN 1 ELSE 0 END),
                                  SUM(CASE WHEN quality='OK' AND retrieval_ts>=?
                                           THEN 1 ELSE 0 END)
                           FROM observations
                           WHERE symbol=? AND retrieval_ts>=?
                             AND retrieval_ts<=?""",
                        (transition,symbol,first_route,now.isoformat())
                    ).fetchone()
                    session_iex['observed_after_route'] += int(counts[0] or 0)>0
                    session_iex['valid_after_route'] += int(counts[1] or 0)>0
                    session_iex['valid_after_08_et'] += int(counts[2] or 0)>0
                    # Retrieval after 08:00 does not prove the underlying IEX
                    # trade happened after 08:00. Audit source time separately.
                    fresh_source = False
                    for (source_ts,) in db.execute(
                        """SELECT source_ts FROM observations
                           WHERE symbol=? AND quality='OK'
                             AND retrieval_ts>=? AND retrieval_ts<=?
                             AND retrieval_ts>=?""",
                        (symbol, first_route, now.isoformat(), transition)
                    ):
                        if _source_at_or_after(source_ts, transition):
                            fresh_source = True
                            break
                    session_iex['valid_source_after_08_et'] += int(fresh_source)
                    if fresh_source:
                        # Audit identity, not BUY; no prices or retrospectively
                        # reconstructed entry points are inferred here.
                        session_iex['converted_symbols'].append(symbol)
                session_iex['note'] = (
                    'valid_after_08_et counts retrievals; '
                    'valid_source_after_08_et requires source trade time >=08:00 ET. '
                    'Prospective audit only, not BUY.'
                )
                session_iex['status']='PROSPECTIVE_SHADOW_NOT_BUY'
                result['v0412_session_iex_conversion']=session_iex
            result['evaluation_states'] = dict(db.execute(
                'SELECT e.status,COUNT(*) FROM evaluations e JOIN observations o ON o.id=e.observation_id WHERE o.run_id=? GROUP BY e.status',
                (run_id,)).fetchall())
            result['model_readiness'] = {
                'status': 'BLOCKED_SEMANTIC_EVIDENCE' if ok else 'NO_VALID_OBSERVATIONS',
                'activity_confirmable_packets': 0,
            }
            if _table_exists(db, 'evidence'):
                packets=db.execute(
                    'SELECT ev.payload FROM evidence ev JOIN observations o ON o.id=ev.observation_id WHERE o.run_id=?',
                    (run_id,)).fetchall()
                activity_ready=0
                for (raw,) in packets:
                    packet=json.loads(raw)
                    baseline=packet.get('valid_activity_baseline') or {}
                    rvol=packet.get('rvol')
                    if isinstance(rvol,(int,float)) and baseline.get('value') is True and baseline.get('provenance'):
                        activity_ready += 1
                result['model_readiness'] = {
                    'status': 'ACTIVITY_EVIDENCE_AVAILABLE' if activity_ready else ('BLOCKED_SEMANTIC_EVIDENCE' if ok else 'NO_VALID_OBSERVATIONS'),
                    'activity_confirmable_packets': activity_ready,
                }
            if _table_exists(db, 'semantic_shadow'):
                shadow_rows=db.execute(
                    'SELECT s.payload FROM semantic_shadow s JOIN observations o ON o.id=s.observation_id WHERE o.run_id=?',
                    (run_id,)
                ).fetchall()
                shadow={'packets':len(shadow_rows),'with_history_samples':0,'with_observed_volume_ratio':0,'new_observed_highs':0,'two_positive_intervals':0}
                for (raw,) in shadow_rows:
                    p=json.loads(raw)
                    if int(p.get('same_clock_volume_sample_count') or 0) > 0:
                        shadow['with_history_samples'] += 1
                    if isinstance(p.get('observed_same_clock_volume_ratio'),(int,float)):
                        shadow['with_observed_volume_ratio'] += 1
                    if p.get('new_observed_high') is True:
                        shadow['new_observed_highs'] += 1
                    if int(p.get('consecutive_positive_intervals') or 0) >= 2:
                        shadow['two_positive_intervals'] += 1
                result['semantic_shadow']=shadow
            if _table_exists(db, 'candidate_v034_events'):
                candidate_states=dict(db.execute(
                    'SELECT c.state,COUNT(*) FROM candidate_v034_events c JOIN observations o ON o.id=c.observation_id WHERE o.run_id=? GROUP BY c.state',
                    (run_id,)
                ).fetchall())
                candidate_lanes=dict(db.execute(
                    'SELECT c.lane,COUNT(*) FROM candidate_v034_events c JOIN observations o ON o.id=c.observation_id WHERE o.run_id=? GROUP BY c.lane',
                    (run_id,)
                ).fetchall())
                signals_total=db.execute('SELECT COUNT(*) FROM candidate_v034_signals').fetchone()[0] if _table_exists(db,'candidate_v034_signals') else 0
                last_candidate=None
                if signals_total:
                    s=db.execute('SELECT symbol,retrieval_ts,lane,state,change_pct,proof FROM candidate_v034_signals ORDER BY id DESC LIMIT 1').fetchone()
                    last_candidate=dict(zip(('symbol','retrieval_ts','lane','state','change_pct','proof'),s))
                result['candidate_v034']={
                    'status':'CANDIDATE_SHADOW_ONLY',
                    'states':candidate_states,
                    'lanes':candidate_lanes,
                    'signals_total':signals_total,
                    'last_signal':last_candidate,
                }
            if _table_exists(db,'candidate_v034r2_events'):
                r2_states=dict(db.execute(
                    'SELECT c.state,COUNT(*) FROM candidate_v034r2_events c JOIN observations o ON o.id=c.observation_id WHERE o.run_id=? GROUP BY c.state',
                    (run_id,)
                ).fetchall())
                r2_total=db.execute('SELECT COUNT(*) FROM candidate_v034r2_signals').fetchone()[0] if _table_exists(db,'candidate_v034r2_signals') else 0
                r2_last=None
                if r2_total:
                    s=db.execute('SELECT symbol,retrieval_ts,lane,state,change_pct,proof FROM candidate_v034r2_signals ORDER BY id DESC LIMIT 1').fetchone()
                    r2_last=dict(zip(('symbol','retrieval_ts','lane','state','change_pct','proof'),s))
                result['candidate_v034r2']={
                    'status':'CANDIDATE_SHADOW_CHALLENGER',
                    'states':r2_states,
                    'signals_total':r2_total,
                    'last_signal':r2_last,
                }
            if _table_exists(db,'scout_runs'):
                sr=db.execute(
                    'SELECT universe_count,eligible_count,selected_count,sticky_count,fetch_seconds,total_seconds FROM scout_runs WHERE run_id=?',
                    (run_id,)
                ).fetchone()
                if sr:
                    result['fast_scout']={
                        'status':'DATA_GAP' if int(sr[1] or 0) == 0 else 'PASS',
                        'evidence_scope':'LATEST_STORED_RUN',
                        'checkpoint_is_current_cycle':result['checkpoint_is_current_cycle'],
                        'universe_count':sr[0],
                        'eligible_count':sr[1],
                        'selected_count':sr[2],
                        'sticky_count':sr[3],
                        'fetch_seconds':sr[4],
                        'total_seconds':sr[5],
                    }
            previous = db.execute('SELECT started FROM runs WHERE id<? ORDER BY id DESC LIMIT 1', (run_id,)).fetchone()
            if previous:
                result['cadence_gap_seconds'] = round((datetime.fromisoformat(started)-datetime.fromisoformat(previous[0])).total_seconds(), 3)
                previous_et = datetime.fromisoformat(previous[0]).astimezone(ZoneInfo('America/New_York'))
                result['cadence']['status'] = ('INVALID_SEQUENCE' if result['cadence_gap_seconds'] <= 0 else 'SESSION_BOUNDARY' if previous_et.date() != datetime.fromisoformat(started).astimezone(ZoneInfo('America/New_York')).date()
                    else 'MISSED_TARGET' if result['cadence_gap_seconds'] > cadence_target_seconds else 'WITHIN_TARGET')
                result['cadence']['observed_gap_seconds'] = result['cadence_gap_seconds']
                from .cadence import dispatch_wait
                previous_health = path.parent / 'previous-health.json'
                prior = json.loads(previous_health.read_text()) if previous_health.exists() else {}
                compensation = prior.get('cadence', {}).get('dispatch_compensation_seconds', 0)
                result['cadence']['dispatch_compensation_seconds'] = dispatch_wait(
                    [started, previous[0]], now, cadence_target_seconds, compensation)['latency_compensation_seconds']
            if _table_exists(db, 'fast_path_events'):
                fp = db.execute('SELECT MAX(retrieval_ts),COUNT(*) FROM fast_path_events WHERE retrieval_ts>=? AND retrieval_ts<=?', (started,now.isoformat())).fetchone()
                fp_latest = db.execute('SELECT retrieval_ts FROM fast_path_events ORDER BY id DESC LIMIT 1').fetchone()
                result['fast_path'].update(current_cycle_events=int(fp[1] or 0) if result['checkpoint_is_current_cycle'] else 0, current_cycle_latest_ts=fp[0] if result['checkpoint_is_current_cycle'] else None, latest_stored_run_events=int(fp[1] or 0),
                                          last_recorded_ts=fp_latest[0] if fp_latest else None, authoritative=False, buy=False)
                result['fast_path']['status'] = ('FAIL' if fast_path_outcome in ('failure','cancelled') else
                    'NOT_RUN' if fast_path_outcome == 'skipped' else
                    'EXPECTED_PREMARKET_ROUTING_ONLY' if fast_path_mode == 'PREMARKET_ROUTING_ONLY' else
                    'CURRENT_SHADOW_EVIDENCE' if int(fp[1] or 0) and result['checkpoint_is_current_cycle'] else 'NO_CURRENT_EVIDENCE')
            if fast_path_outcome in ('failure','cancelled'):
                result['health'] = 'FAIL'
            if status == 'FAILED':
                result['health'] = 'FAIL'
            elif status == 'PREMARKET_ROUTING_ONLY':
                # Expected provider limitation: discovery/routing is alive, but frozen model evidence
                # remains intentionally blocked until an entitled real-time feed is available.
                if result['health'] == 'PASS':
                    result['health'] = 'DEGRADED'
                result['evidence_health'] = 'EXPECTED_PREMARKET_ROUTING_ONLY'
            elif status == 'MONITOR_DATA_GAP':
                if result['health'] == 'PASS':
                    result['health'] = 'DEGRADED'
                result['evidence_health'] = 'UNEXPECTED_MODEL_DATA_GAP'
            elif total > 0 and ok == 0 and result['health'] == 'PASS':
                result['health'] = 'DEGRADED'
                result['evidence_health'] = 'ROUTING_ONLY_NO_VALID_MODEL_OBSERVATIONS'
        result['candidate_count'] = db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0]
        if _table_exists(db, 'bridge_publications'):
            result['pending_bridge_events'] = db.execute(
                'SELECT COUNT(*) FROM outbox o LEFT JOIN bridge_publications b ON b.event_key=o.event_key WHERE b.event_key IS NULL'
            ).fetchone()[0]
        else:
            result['pending_bridge_events'] = db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]
        if _table_exists(db, 'signals'):
            signal = db.execute('SELECT id,symbol,retrieval_ts,lane,band,change_pct,early_credit FROM signals WHERE replay=0 ORDER BY id DESC LIMIT 1').fetchone()
            if signal:
                result['last_signal'] = dict(zip(('id','symbol','retrieval_ts','lane','band','change_pct','early_credit'), signal))
        if not observation_window and not result['checkpoint_is_current_cycle']:
            # Keep the established health enum and evidence diagnostics intact.
            # Freshness is orthogonal to provider/data health.
            result['checkpoint_freshness']='STALE_OUTSIDE_SESSION'
        else:
            result['checkpoint_freshness']='CURRENT' if result['checkpoint_is_current_cycle'] else 'STALE'
        if observation_window and (not result['checkpoint_is_current_cycle'] or result['fast_scout']['status'] == 'DATA_GAP' or result['cadence']['status'] in ('MISSED_TARGET','INVALID_SEQUENCE')) and result['health'] == 'PASS':
            result['health'] = 'DEGRADED'
        if observation_window and result['checkpoint_is_current_cycle'] and fast_path_outcome == 'success' and fast_path_mode == 'MINUTE_LOOP' and result['fast_path']['status'] in ('NO_DATA','NO_CURRENT_EVIDENCE') and result['health'] == 'PASS':
            result['health'] = 'DEGRADED'
        recovery_path = path.parent / 'recovery-status.json'
        if recovery_path.exists():
            result['recovery'] = json.loads(recovery_path.read_text())
        if result['pending_bridge_events'] and result['health'] == 'PASS':
            result['health'] = 'DEGRADED'
    finally:
        db.close()
    result['reason_codes'] = health_reasons(result)
    return result

def health_reasons(result):
    codes = []
    if result['workflow']['scan_rc']: codes.append('SCAN_FAILED')
    if result['workflow']['bridge_rc']: codes.append('BRIDGE_FAILED')
    if (result.get('latest_run') or {}).get('status') == 'FAILED': codes.append('RUN_FAILED')
    if result['fast_path']['status'] == 'FAIL': codes.append('FAST_PATH_FAILED')
    if result.get('evidence_health'): codes.append(result['evidence_health'])
    if result['pending_bridge_events']: codes.append('BRIDGE_BACKLOG')
    if result['observation_window_active']:
        if not result['checkpoint_is_current_cycle']: codes.append('CHECKPOINT_STALE')
        if result['fast_scout']['status'] == 'DATA_GAP': codes.append('SCOUT_DATA_GAP')
        if result['cadence']['status'] in ('MISSED_TARGET','INVALID_SEQUENCE'): codes.append('CADENCE_' + result['cadence']['status'])
        if result['checkpoint_is_current_cycle'] and result['fast_path'].get('workflow_outcome') == 'success' and result['fast_path'].get('mode') == 'MINUTE_LOOP' and result['fast_path']['status'] in ('NO_DATA','NO_CURRENT_EVIDENCE'): codes.append('FAST_PATH_NO_CURRENT_EVIDENCE')
    return sorted(set(codes))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--scan-rc', type=int, default=0)
    p.add_argument('--bridge-rc', type=int, default=0)
    p.add_argument('--fast-path-outcome', choices=['success','failure','cancelled','skipped'])
    p.add_argument('--fast-path-mode', choices=['PREMARKET_ROUTING_ONLY','MINUTE_LOOP','UNKNOWN'], default='UNKNOWN')
    p.add_argument('--config', default='config/radar.json')
    args=p.parse_args()
    target = int(json.loads(Path(args.config).read_text()).get('cadence_target_seconds',300))
    payload=build(args.db,args.scan_rc,args.bridge_rc,args.fast_path_outcome,target,fast_path_mode=args.fast_path_mode)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print(json.dumps(payload,sort_keys=True))

if __name__=='__main__':
    main()
