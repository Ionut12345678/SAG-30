"""Machine-readable operational heartbeat for SAG-30 infrastructure.

This reports what the collector actually did. It does not infer or modify frozen model gates.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .model import SPEC_SHA256

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def _table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

def build(db_path, scan_rc=0, bridge_rc=0):
    result = {
        'generated_ts': utcnow(),
        'frozen_version': 'SAG-30 Early Radar v0.3.3 FROZEN SHADOW',
        'spec_sha256': SPEC_SHA256,
        'workflow': {'scan_rc': int(scan_rc), 'bridge_rc': int(bridge_rc)},
        'health': 'FAIL' if int(scan_rc) else ('DEGRADED' if int(bridge_rc) else 'PASS'),
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
    }
    path = Path(db_path)
    if not path.exists():
        result['health'] = 'FAIL'
        result['detail'] = 'audit database missing'
        return result
    db = sqlite3.connect(path)
    try:
        latest = db.execute('SELECT id,started,finished,status,detail FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        if latest:
            run_id, started, finished, status, detail = latest
            result['latest_run'] = {'id': run_id, 'started': started, 'finished': finished, 'status': status, 'detail': detail}
            total, ok = db.execute("SELECT COUNT(*),SUM(CASE WHEN quality='OK' THEN 1 ELSE 0 END) FROM observations WHERE run_id=?", (run_id,)).fetchone()
            total, ok = int(total or 0), int(ok or 0)
            result['observations'] = {'total': total, 'ok': ok, 'data_quality': total-ok}
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
                        'status':'PASS',
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
            if status == 'FAILED':
                result['health'] = 'FAIL'
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
        if result['pending_bridge_events'] and result['health'] == 'PASS':
            result['health'] = 'DEGRADED'
    finally:
        db.close()
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--scan-rc', type=int, default=0)
    p.add_argument('--bridge-rc', type=int, default=0)
    args=p.parse_args()
    payload=build(args.db,args.scan_rc,args.bridge_rc)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print(json.dumps(payload,sort_keys=True))

if __name__=='__main__':
    main()
