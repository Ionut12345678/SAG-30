"""Read-only, censored prospective detection audit. Never reconstructs a signal."""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .core import LABEL, early_band


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone missing')
    return parsed.astimezone(timezone.utc)


def build(db_path, session, watch_path=None, as_of=None):
    cutoff = as_of or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError('as_of must be timezone aware')
    cohorts = {}
    valid = defaultdict(list)
    events = defaultdict(list)
    counts = Counter()
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'scout_history' in tables:
            for r in db.execute('SELECT * FROM scout_history WHERE session=? ORDER BY retrieval_ts,run_id,symbol', (session,)):
                if stamp(r['retrieval_ts']) > cutoff:
                    continue
                counts['scout_samples'] += 1
                cohorts.setdefault(r['symbol'], {'symbol': r['symbol'], 'first_discovery_retrieval_ts': r['retrieval_ts'],
                    'first_discovery_change_pct': r['change_pct'], 'first_discovery_source_ts': None,
                    'first_discovery_price': None, 'discovery_source_quality': 'UNKNOWN_ROUTING_ONLY',
                    'first_deep_observation': None, 'first_watch': None})
        for r in db.execute('SELECT * FROM observations ORDER BY retrieval_ts,id'):
            retrieved = stamp(r['retrieval_ts'])
            if retrieved > cutoff or retrieved.astimezone(ZoneInfo('America/New_York')).date().isoformat() != session:
                continue
            counts['deep_samples'] += 1
            counts['valid_deep_samples' if r['quality']=='OK' else 'data_quality_deep_samples'] += 1
            c = cohorts.setdefault(r['symbol'], {'symbol':r['symbol'], 'first_discovery_retrieval_ts': None,
                'first_discovery_change_pct': None, 'first_discovery_source_ts':None,
                'first_discovery_price':None, 'discovery_source_quality':'UNKNOWN_NO_SCOUT_HISTORY',
                'first_deep_observation':None, 'first_watch':None})
            packet = {k:r[k] for k in ('retrieval_ts','source_ts','price','change_pct','quality','reason')}
            if c['first_deep_observation'] is None:
                c['first_deep_observation'] = packet
            if c['first_discovery_retrieval_ts'] and stamp(c['first_discovery_retrieval_ts'])==retrieved:
                c['first_discovery_source_ts'], c['first_discovery_price'] = r['source_ts'], r['price']
                c['discovery_source_quality'] = r['quality']
            if r['quality']=='OK' and r['change_pct'] is not None:
                # Independently reject impossible source times even in old databases.
                try:
                    age = (retrieved-stamp(r['source_ts'])).total_seconds()
                except (ValueError, TypeError, AttributeError):
                    age = -1
                if age < 0 or age > 900:
                    counts['invalid_stored_ok_source_samples'] += 1
                    continue
                valid[r['symbol']].append(packet)
        if 'fast_path_events' in tables:
            for r in db.execute('SELECT symbol,retrieval_ts,state,change_pct,source FROM fast_path_events WHERE session=? ORDER BY retrieval_ts,id', (session,)):
                if stamp(r['retrieval_ts']) <= cutoff:
                    events[r['symbol']].append(dict(r))
        run_denominators = []
        if 'scout_runs' in tables:
            for r in db.execute('SELECT * FROM scout_runs ORDER BY run_id'):
                t = stamp(r['started_ts'])
                if t <= cutoff and t.astimezone(ZoneInfo('America/New_York')).date().isoformat()==session:
                    run_denominators.append(dict(r))
        stored_first_seen = []
        if 'model_state' in tables:
            stored_first_seen = [dict(r) for r in db.execute('SELECT symbol,first_seen,first_radar_seen,first_radar_pct FROM model_state ORDER BY symbol') if r['symbol'] in cohorts]
    if watch_path and Path(watch_path).exists():
        seen = set()
        for line in Path(watch_path).read_text().splitlines():
            if not line.strip(): continue
            w = json.loads(line)
            if w['session'] != session: continue
            if w['symbol'] in seen: raise ValueError('duplicate immutable first WATCH')
            seen.add(w['symbol'])
            # Availability is capture time, not the earlier underlying snapshot.
            capture = w.get('captured_at_utc')
            if not capture or stamp(capture)>cutoff: continue
            if w['symbol'] in cohorts:
                cohorts[w['symbol']]['first_watch'] = w
    for symbol,c in sorted(cohorts.items()):
        c['logged_shadow_events'] = events[symbol]
        discovery = c['first_discovery_retrieval_ts']
        basis = discovery or (c['first_deep_observation'] or {}).get('retrieval_ts')
        pct = c['first_discovery_change_pct'] if discovery else (c['first_deep_observation'] or {}).get('change_pct')
        c['detection_band'] = early_band(pct)
        c['late_detection'] = None if pct is None else pct>=20
        c['early_credit'] = 0  # Audit discovery/WATCH is not frozen EARLY-HOT.
        later = [p for p in valid[symbol] if basis and stamp(p['retrieval_ts'])>stamp(basis)]
        c['later_valid_samples'] = len(later)
        c['observed_crossings'] = {}
        for threshold in (15,20,30,50):
            match = next((p for p in later if p['change_pct']>=threshold),None)
            # Already at/above target at detection cannot count as prospective lead.
            eligible = pct is not None and pct<threshold
            c['observed_crossings'][str(threshold)] = ({**match,
                'lead_seconds_from_discovery':(stamp(match['retrieval_ts'])-stamp(basis)).total_seconds(),
                'watch_lead_seconds':(stamp(match['retrieval_ts'])-stamp(c['first_watch']['captured_at_utc'])).total_seconds()
                    if c['first_watch'] and stamp(match['retrieval_ts'])>stamp(c['first_watch']['captured_at_utc']) else None}
                if eligible and match else None)
        c['outcome'] = 'CENSORED_NO_FOLLOWUP' if not later else 'OBSERVED_LATER_30' if c['observed_crossings']['30'] else 'CENSORED_NO_OBSERVED_30'
        c['false_positive'] = 'UNKNOWN_CENSORED'
        c['execution_actionable'] = 'UNKNOWN'
    return {'label': LABEL, 'status':'READ_ONLY_PROSPECTIVE_AUDIT', 'session':session,
        'as_of':cutoff.isoformat(), 'counts':dict(counts), 'cohort_count':len(cohorts),
        'run_denominators':run_denominators, 'stored_global_first_seen':stored_first_seen,
        'cohorts':[cohorts[s] for s in sorted(cohorts)],
        'limitations':['Discovery is routing, not EARLY-HOT. Missing discovery source/price stays UNKNOWN.',
            'Crossings are later valid deep snapshots, not exact move onset or executable gains.',
            'No inferred WATCH, FLOW or precursor signal; only original logged events.',
            'No complete-session coverage or false-positive rate established; gaps and unobserved winners remain censored.']}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True);p.add_argument('--session',required=True)
    p.add_argument('--watch-journal');p.add_argument('--as-of');p.add_argument('--out',required=True)
    a=p.parse_args()
    result=build(a.db,a.session,a.watch_journal,stamp(a.as_of) if a.as_of else None)
    Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')

if __name__=='__main__': main()
