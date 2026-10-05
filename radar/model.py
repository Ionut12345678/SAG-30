"""Frozen specification interpreter. Undefined semantic gates require sourced evidence."""
import hashlib
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from .core import LABEL, early_band, utcnow

SPEC_SHA256 = '65c3c170d42e0b4bb8eca75b38d32a3c551f1ba7101eef825c745d588fdabc31'

def verify_spec():
    if hashlib.sha256(Path('rules/SAG-30-v0.3.3-FROZEN.txt').read_bytes()).hexdigest() != SPEC_SHA256:
        raise ValueError('Frozen specification checksum mismatch')

def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS model_state(symbol TEXT PRIMARY KEY, first_seen TEXT NOT NULL, first_radar_seen TEXT,
      first_radar_pct REAL, state TEXT NOT NULL, lane TEXT NOT NULL, memory TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, observation_id INTEGER UNIQUE,
      retrieval_ts TEXT NOT NULL, source_ts TEXT, lane TEXT NOT NULL, band TEXT NOT NULL, change_pct REAL, baseline_close REAL NOT NULL,
      early_credit INTEGER NOT NULL, replay INTEGER NOT NULL, proof TEXT NOT NULL, spec_sha256 TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS evidence(observation_id INTEGER PRIMARY KEY, recorded_ts TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS milestones(signal_id INTEGER NOT NULL, target INTEGER NOT NULL, observation_id INTEGER NOT NULL,
      retrieval_ts TEXT NOT NULL, PRIMARY KEY(signal_id,target));
    CREATE TRIGGER IF NOT EXISTS immutable_first_seen BEFORE UPDATE OF first_seen ON model_state
      WHEN NEW.first_seen != OLD.first_seen BEGIN SELECT RAISE(ABORT,'first_seen immutable'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_first_radar BEFORE UPDATE OF first_radar_seen ON model_state
      WHEN OLD.first_radar_seen IS NOT NULL AND NEW.first_radar_seen != OLD.first_radar_seen
      BEGIN SELECT RAISE(ABORT,'first_radar_seen immutable'); END;
    ''')

def evaluate(db, observation_id, evidence=None, replay=False):
    """Evidence is attached prospectively to this exact source snapshot, never historical."""
    init(db)
    obs = db.execute('SELECT symbol,retrieval_ts,source_ts,quality,price,change_pct,payload FROM observations WHERE id=?', (observation_id,)).fetchone()
    symbol, retrieved, source, quality, price, pct, payload = obs
    existing = db.execute('SELECT memory,lane,first_radar_seen,state FROM model_state WHERE symbol=?', (symbol,)).fetchone()
    memory = json.loads(existing[0]) if existing else {}
    lane = existing[1] if existing else 'UNKNOWN'
    first_radar = existing[2] if existing else None
    session = datetime.fromisoformat(retrieved).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    same_session = memory.get('session') == session
    if not same_session:
        memory = {'session': session}
        lane = 'UNKNOWN'
    state, reason = 'UNKNOWN/DATA_QUALITY', 'Missing, conflicting or unsynchronized evidence'
    evidence = evidence or {}
    evidence_json = json.dumps(evidence,sort_keys=True)
    db.execute('INSERT INTO evidence VALUES(?,?,?,?)', (observation_id,utcnow(),evidence_json,hashlib.sha256(evidence_json.encode()).hexdigest()))
    matched = evidence.get('source_ts') == source and evidence.get('symbol') == symbol
    # Verified facts need a citation and may not be silently inferred from raw volume.
    def fact(name):
        item = evidence.get(name, {}) if matched else {}
        return item.get('value') is True and bool(item.get('provenance'))
    if quality == 'OK':
        for signal_id, baseline in db.execute('SELECT id,baseline_close FROM signals WHERE symbol=? AND retrieval_ts<=? AND replay=0', (symbol,retrieved)).fetchall():
            for target in (30,50):
                if price >= baseline * (1 + target / 100):
                    db.execute('INSERT OR IGNORE INTO milestones VALUES(?,?,?,?)', (signal_id,target,observation_id,retrieved))
        state, reason = 'RADAR-LOW', 'Raw activity is interest only; no valid RVOL baseline'
        rvol = evidence.get('rvol') if matched else None
        activity = (isinstance(rvol, (int,float)) and rvol >= 3 and fact('valid_activity_baseline'))
        if activity:
            state, reason = 'RADAR/WATCH', 'Confirmed activity; waiting for chronological lane gates'
            if first_radar is None:
                first_radar = retrieved
            requested_lane = evidence.get('lane')
            if requested_lane in ('FRESH','SECOND_IMPULSE','OVERNIGHT') and fact('lane_classification'):
                lane = requested_lane
            allowed_lane = lane == 'FRESH' or (lane == 'SECOND_IMPULSE' and all(fact(n) for n in ('energy_memory','reset','rewake','no_absorption'))) or (lane == 'OVERNIGHT' and all(fact(n) for n in ('preclose_ah_event','price_response','hold','premarket_continuation')))
            if allowed_lane and fact('price_conversion') and fact('acceptance_reclaim') and not memory.get('accepted_at'):
                memory.update(accepted_at=retrieved, accepted_source=source, accepted_price=price, accepted_pct=pct, high=price, no_high=0, positive=0)
                reason = 'Acceptance recorded; subsequent expansion still required'
            elif allowed_lane and memory.get('accepted_at') and retrieved > memory['accepted_at'] and datetime.fromisoformat(source.replace('Z','+00:00')) > datetime.fromisoformat(memory['accepted_source'].replace('Z','+00:00')):
                # Latest-trade price proves a new high prospectively; daily highs cannot backdate proof.
                high = price
                new_high = high > memory['high']
                positive = price > memory.get('previous_price',memory['accepted_price']) and new_high
                memory['positive'] = memory.get('positive',0) + 1 if positive else 0
                memory['no_high'] = 0 if new_high else memory.get('no_high',0) + 1
                proof = 'new high after acceptance' if new_high else ('reacceleration >=2pp' if pct - memory['accepted_pct'] >= 2 else None)
                if memory['positive'] >= 2:
                    proof = 'two positive intervals with rising observed highs'
                # Absorption and failed acceptance cannot be quantified from the frozen prose.
                safe = fact('no_absorption') and fact('acceptance_still_valid') and not fact('failed_acceptance')
                if proof and safe and memory['no_high'] < 2 and not memory.get('hot'):
                    band = early_band(pct)
                    rewake_pct = evidence.get('rewake_pct')
                    lane_b_early = lane != 'SECOND_IMPULSE' or (isinstance(rewake_pct,(int,float)) and math.isfinite(rewake_pct) and rewake_pct < 15)
                    credit = int(pct < 20 and lane_b_early and not replay)
                    state = 'LATE-RADAR' if pct >= 20 else 'EARLY-HOT'
                    signal = db.execute('INSERT INTO signals(symbol,observation_id,retrieval_ts,source_ts,lane,band,change_pct,baseline_close,early_credit,replay,proof,spec_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (symbol,observation_id,retrieved,source,lane,band,pct,json.loads(payload)['prevDailyBar']['c'],credit,int(replay),proof,SPEC_SHA256))
                    memory['hot'] = True
                    reason = proof
                    if not replay:
                        message = f'{LABEL}\n{symbol}: {state} ({lane}), {pct:+.2f}%, {band}\nRETRIEVAL_TS={retrieved}\nSOURCE_TS={source}\n{proof}'
                        db.execute('INSERT OR IGNORE INTO outbox(event_key,created_ts,message) VALUES(?,?,?)', (f'signal:{signal.lastrowid}',utcnow(),message))
                else:
                    reason = 'WAIT: expansion or semantic acceptance/absorption evidence unresolved'
                memory['high'] = max(memory['high'],high)
                memory['previous_price'] = price
        if existing and same_session and existing[3] in ('EARLY-HOT','LATE-RADAR') and not fact('failed_acceptance'):
            state = existing[3]
        if matched and fact('failed_acceptance'):
            memory = {'session': session}
            state, reason = 'CLOSED-NOISE/FAIL', 'Sourced failed acceptance; no promotion'
    db.execute('INSERT INTO model_state VALUES(?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET first_radar_seen=COALESCE(model_state.first_radar_seen,excluded.first_radar_seen),first_radar_pct=COALESCE(model_state.first_radar_pct,excluded.first_radar_pct),state=excluded.state,lane=excluded.lane,memory=excluded.memory',
        (symbol,retrieved,first_radar,pct if first_radar == retrieved else None,state,lane,json.dumps(memory)))
    db.execute('UPDATE evaluations SET status=?,detail=?,evaluated_ts=? WHERE observation_id=?', (state,reason,utcnow(),observation_id))
    return state
