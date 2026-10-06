import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from .core import LABEL, open_db, record, utcnow
from .model import evaluate, verify_spec
from .evidence import observed_packet
from .semantic_shadow import build as build_semantic_shadow
from .volume_baseline_shadow import ingest as ingest_shadow_volume_baseline, historical_range
from .candidate_v034 import evaluate as evaluate_candidate_v034

log = logging.getLogger('radar')

def request(url, headers=None, data=None):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers or {}, data=data), timeout=30) as response:
                body = response.read()
                retrieved = utcnow()
            return json.loads(body), retrieved
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f'Provider HTTP {exc.code}') from None
            time.sleep(min(int(exc.headers.get('Retry-After', '2')), 30))
    raise RuntimeError('Request retries exhausted')

def session_window(now):
    local = now.astimezone(ZoneInfo('America/New_York'))
    return local.weekday() < 5 and 4 <= local.hour < 20

def load_universe(path):
    with open(path, newline='') as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError('Configure a dated U.S. small-cap universe; sample file is intentionally empty')
    symbols = []
    for row in rows:
        symbol = row['symbol'].strip().upper()
        if not symbol or not all(c.isalnum() or c in '.-' for c in symbol):
            raise ValueError('Invalid symbol in universe')
        if float(row['market_cap_usd']) <= 0 or not row['as_of']:
            raise ValueError('Universe requires positive market cap and as_of provenance')
        symbols.append(symbol)
    return sorted(set(symbols))

def load_market_caps(path):
    with open(path, newline='') as file:
        return {row['symbol'].strip().upper(): float(row['market_cap_usd']) for row in csv.DictReader(file)}

def route_shortlist(snapshots, market_caps, changes, limit, accelerations=None, volume_impulses=None):
    """Diversified discovery routing only; these rankings are never frozen model gates."""
    accelerations=accelerations or {}
    volume_impulses=volume_impulses or {}
    symbols=list(snapshots)
    def volume(symbol):
        return float((snapshots[symbol].get('dailyBar') or {}).get('v') or 0)
    def turnover(symbol):
        price=float((snapshots[symbol].get('latestTrade') or {}).get('p') or 0)
        cap=float(market_caps.get(symbol) or 0)
        return volume(symbol)*price/cap if cap > 0 else 0
    routes=[
        sorted(symbols,key=lambda s:(turnover(s),s),reverse=True),
        sorted(symbols,key=lambda s:(float(changes.get(s) or 0),s),reverse=True),
        sorted(symbols,key=lambda s:(float(accelerations.get(s) or 0),s),reverse=True),
        sorted(symbols,key=lambda s:(float(volume_impulses.get(s) or 0),s),reverse=True),
        sorted(symbols,key=lambda s:(volume(s),s),reverse=True),
    ]
    selected=[]
    seen=set()
    for index in range(max((len(route) for route in routes), default=0)):
        for route in routes:
            if index < len(route) and route[index] not in seen:
                selected.append(route[index])
                seen.add(route[index])
                if len(selected) >= limit:
                    return selected
    return selected

def routing_view(snapshot, retrieved, max_age):
    """Return a fresh routing-only price view; never changes model DATA_QUALITY."""
    previous=snapshot.get('prevDailyBar') or {}
    close=previous.get('c')
    if not isinstance(close,(int,float)) or close <= 0:
        return None
    retrieval=datetime.fromisoformat(retrieved)
    for key,price_key in (('latestTrade','p'),('minuteBar','c')):
        item=snapshot.get(key) or {}
        price=item.get(price_key)
        stamp=item.get('t')
        if not isinstance(price,(int,float)) or price <= 0 or not stamp:
            continue
        try:
            source=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            age=(retrieval-source).total_seconds()
        except (TypeError,ValueError,AttributeError):
            continue
        if 0 <= age <= max_age:
            normalized=dict(snapshot)
            normalized['latestTrade']={'p':float(price),'t':stamp}
            return normalized, float((float(price)/float(close)-1)*100), key
    return None


def fetch_snapshot_batches(symbols, headers, feed, workers=8):
    """Fetch snapshot batches concurrently, then return them in deterministic universe order."""
    batches=[(offset,symbols[offset:offset+100]) for offset in range(0,len(symbols),100)]
    if not batches:
        return []
    workers=max(1,min(int(workers or 1),len(batches)))
    def one(item):
        offset,batch=item
        started=utcnow()
        url='https://data.alpaca.markets/v2/stocks/snapshots?' + urlencode({'symbols': ','.join(batch), 'feed': feed})
        result,retrieved=request(url,headers)
        return offset,batch,started,result,retrieved
    completed=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(one,item) for item in batches]
        for future in as_completed(futures):
            completed.append(future.result())
    return sorted(completed,key=lambda x:x[0])

def routing_momentum(db, symbol, observation_id, current_change, snapshot, market_cap, retrieval_ts):
    """Routing-only price acceleration and fresh turnover impulse, normalized per minute."""
    if not isinstance(current_change,(int,float)):
        return 0.0,0.0
    prior=db.execute(
        "SELECT retrieval_ts,change_pct,payload FROM observations WHERE symbol=? AND id<? AND change_pct IS NOT NULL ORDER BY id DESC LIMIT 1",
        (symbol,observation_id)
    ).fetchone()
    if not prior:
        return 0.0,0.0
    try:
        current_dt=datetime.fromisoformat(retrieval_ts)
        prior_dt=datetime.fromisoformat(prior[0])
        if current_dt.astimezone(ZoneInfo('America/New_York')).date()!=prior_dt.astimezone(ZoneInfo('America/New_York')).date():
            return 0.0,0.0
        minutes=(current_dt-prior_dt).total_seconds()/60.0
        if minutes<=0 or minutes>60:
            return 0.0,0.0
        acceleration=(float(current_change)-float(prior[1]))/minutes
        prior_payload=json.loads(prior[2])
        current_volume=float((snapshot.get('dailyBar') or {}).get('v') or 0)
        prior_volume=float((prior_payload.get('dailyBar') or {}).get('v') or 0)
        price=float((snapshot.get('latestTrade') or {}).get('p') or (snapshot.get('minuteBar') or {}).get('c') or 0)
        cap=float(market_cap or 0)
        fresh=max(0.0,current_volume-prior_volume)
        impulse=(fresh*price/cap)/minutes if cap>0 and price>0 else 0.0
        return acceleration,impulse
    except (TypeError,ValueError,KeyError,json.JSONDecodeError):
        return 0.0,0.0


def refresh_shadow_volume_baseline(db, symbols, headers, feed, now):
    """Best-effort research backfill for current shortlist; never blocks production."""
    if not symbols:
        return 0
    start,end=historical_range(now)
    bars={}
    page_token=None
    pages=0
    try:
        while pages < 20:
            params={
                'symbols': ','.join(symbols),
                'timeframe': '5Min',
                'start': start,
                'end': end,
                'adjustment': 'raw',
                'feed': feed,
                'limit': 10000,
            }
            if page_token:
                params['page_token']=page_token
            payload,_=request('https://data.alpaca.markets/v2/stocks/bars?' + urlencode(params), headers)
            for symbol,items in (payload.get('bars') or {}).items():
                bars.setdefault(symbol,[]).extend(items or [])
            page_token=payload.get('next_page_token')
            pages += 1
            if not page_token:
                break
        rows=ingest_shadow_volume_baseline(db,bars)
        db.commit()
        log.info('SAG30_SHADOW_BASELINE symbols=%s pages=%s rows=%s',len(symbols),pages,rows)
        return rows
    except Exception as exc:
        log.warning('SAG30_SHADOW_BASELINE unavailable: %s', str(exc))
        return 0


def prime_selected_after_discovery(db, run_id, selected, headers, config, evidence):
    """Prospective second snapshot after shortlist selection and baseline backfill."""
    if not selected:
        return 0
    started=utcnow()
    url='https://data.alpaca.markets/v2/stocks/snapshots?' + urlencode({'symbols': ','.join(selected), 'feed': config['feed']})
    result,retrieved=request(url,headers)
    ok=0
    states={}
    for symbol in selected:
        snapshot=result.get(symbol,{})
        quality=record(db,run_id,symbol,snapshot,started,retrieved,config['max_source_age_seconds'])
        observation_id=db.execute(
            'SELECT MAX(id) FROM observations WHERE run_id=? AND symbol=?',(run_id,symbol)
        ).fetchone()[0]
        packet=observed_packet(db,observation_id,evidence.get(symbol))
        evaluate(db,observation_id,packet)
        build_semantic_shadow(db,observation_id,utcnow())
        state=evaluate_candidate_v034(db,observation_id,utcnow())
        states[state]=states.get(state,0)+1
        ok += int(quality=='OK')
    db.commit()
    log.info('SAG30_POST_DISCOVERY_PRIME selected=%s ok=%s candidate_states=%s',len(selected),ok,sorted(states.items()))
    return len(selected)


def run():
    verify_spec()
    config = json.loads(Path(os.getenv('RADAR_CONFIG', 'config/radar.json')).read_text())
    path = Path(os.getenv('RADAR_DB', 'state/radar.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = open_db(path)
    now = datetime.fromisoformat(utcnow())
    if not session_window(now):
        log.info('Outside configured U.S. observation window')
        return
    run_id = db.execute('INSERT INTO runs(started,status) VALUES(?,?)', (now.isoformat(), 'RUNNING')).lastrowid
    db.commit()
    try:
        keys = [os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY')]
        if not all(keys):
            raise ValueError('Missing ALPACA_API_KEY / ALPACA_SECRET_KEY secrets')
        headers = {'APCA-API-KEY-ID': keys[0], 'APCA-API-SECRET-KEY': keys[1]}
        day = now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        calendar, _ = request('https://paper-api.alpaca.markets/v2/calendar?' + urlencode({'start':day,'end':day}), headers)
        if not calendar:
            db.execute('UPDATE runs SET finished=?,status=? WHERE id=?', (utcnow(), 'CLOSED', run_id))
            db.commit()
            return
        last = db.execute("SELECT started FROM runs WHERE status='DISCOVERY_OK' ORDER BY id DESC LIMIT 1").fetchone()
        broad = last is None or (now - datetime.fromisoformat(last[0])).total_seconds() >= config['discovery_interval_seconds']
        universe = load_universe(config['universe_file'])
        market_caps = load_market_caps(config['universe_file'])
        db.execute('DELETE FROM candidates WHERE expires < ?', (now.isoformat(),))
        candidates = [r[0] for r in db.execute('SELECT symbol FROM candidates ORDER BY symbol')]
        symbols = universe if broad else candidates
        snapshots = {}
        changes = {}
        routing_snapshots = {}
        routing_changes = {}
        routing_fallbacks = 0
        routing_accelerations = {}
        routing_volume_impulses = {}
        evidence_path = Path(config.get('evidence_file', 'config/evidence.json'))
        evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
        if not broad and candidates:
            refresh_shadow_volume_baseline(db, candidates, headers, config['feed'], now)
        if not evidence_path.exists():
            log.warning('SAG30_SEMANTIC_EVIDENCE source=missing path=%s; undefined frozen gates remain WAIT/UNKNOWN', evidence_path)
        fetched_batches=fetch_snapshot_batches(
            symbols, headers, config['feed'], config.get('snapshot_workers',8)
        )
        for offset,batch,started,result,retrieved in fetched_batches:
            for symbol in batch:
                snapshot = result.get(symbol, {})
                quality = record(db, run_id, symbol, snapshot, started, retrieved, config['max_source_age_seconds'])
                observation_id = db.execute('SELECT MAX(id) FROM observations WHERE run_id=? AND symbol=?', (run_id,symbol)).fetchone()[0]
                if quality != 'OK':
                    source_ts, retrieval_ts, reason = db.execute(
                        'SELECT source_ts,retrieval_ts,reason FROM observations WHERE id=?', (observation_id,)
                    ).fetchone()
                    age_seconds = None
                    try:
                        age_seconds = round(
                            (datetime.fromisoformat(retrieval_ts) - datetime.fromisoformat(source_ts.replace('Z', '+00:00'))).total_seconds(),
                            3,
                        )
                    except (TypeError, ValueError, AttributeError):
                        pass
                    log.warning(
                        'SAG30_DATA_QUALITY symbol=%s reason=%s source_ts=%s retrieval_ts=%s age_seconds=%s',
                        symbol, reason, source_ts, retrieval_ts, age_seconds,
                    )
                packet = observed_packet(db, observation_id, evidence.get(symbol))
                evaluate(db, observation_id, packet)
                build_semantic_shadow(db, observation_id, utcnow())
                evaluate_candidate_v034(db, observation_id, utcnow())
                if quality == 'OK':
                    snapshots[symbol] = snapshot
                    changes[symbol] = db.execute('SELECT change_pct FROM observations WHERE id=?', (observation_id,)).fetchone()[0]
                    routing_snapshots[symbol] = snapshot
                    routing_changes[symbol] = changes[symbol]
                    accel,impulse=routing_momentum(
                        db,symbol,observation_id,changes[symbol],snapshot,market_caps.get(symbol),retrieved
                    )
                    routing_accelerations[symbol]=accel
                    routing_volume_impulses[symbol]=impulse
                else:
                    route = routing_view(snapshot, retrieved, config['max_source_age_seconds'])
                    if route:
                        normalized, route_change, route_source = route
                        routing_snapshots[symbol] = normalized
                        routing_changes[symbol] = route_change
                        accel,impulse=routing_momentum(
                            db,symbol,observation_id,route_change,normalized,market_caps.get(symbol),retrieved
                        )
                        routing_accelerations[symbol]=accel
                        routing_volume_impulses[symbol]=impulse
                        if route_source == 'minuteBar':
                            routing_fallbacks += 1
            db.commit()
            quality_counts = db.execute(
                'SELECT quality,reason,COUNT(*) FROM observations WHERE run_id=? AND symbol IN (' +
                ','.join('?' for _ in batch) + ') GROUP BY quality,reason ORDER BY COUNT(*) DESC',
                [run_id, *batch],
            ).fetchall()
            log.info('SAG30_DATA_QUALITY_SUMMARY batch=%s', quality_counts)
            time.sleep(0.4)
        if broad:
            # Multi-route operational discovery only; none of these rankings is a model gate.
            selected = route_shortlist(
                routing_snapshots, market_caps, routing_changes, config['shortlist_limit'],
                routing_accelerations, routing_volume_impulses
            )
            top_accel=sorted(routing_accelerations.items(),key=lambda x:x[1],reverse=True)[:5]
            top_impulse=sorted(routing_volume_impulses.items(),key=lambda x:x[1],reverse=True)[:5]
            log.info('SAG30_ROUTING eligible=%s model_ok=%s minute_fallbacks=%s selected=%s top_accel=%s top_impulse=%s',
                     len(routing_snapshots),len(snapshots),routing_fallbacks,len(selected),top_accel,top_impulse)
            if selected:
                marks = ','.join('?' for _ in selected)
                db.execute('DELETE FROM candidates WHERE symbol NOT IN (' + marks + ')', selected)
            for symbol in selected:
                db.execute('INSERT INTO candidates VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET last_seen=excluded.last_seen,expires=excluded.expires',
                    (symbol, now.isoformat(), now.isoformat(), (now + timedelta(hours=24)).isoformat()))
            if selected:
                marks = ','.join('?' for _ in selected)
                db.execute('DELETE FROM shadow_volume_baseline WHERE symbol NOT IN (' + marks + ')', selected)
                refresh_shadow_volume_baseline(db, selected, headers, config['feed'], now)
                prime_selected_after_discovery(db, run_id, selected, headers, config, evidence)
        if symbols and not snapshots:
            raise ValueError('No fresh valid snapshots; inspect recorded DATA_QUALITY reasons')
        db.execute('UPDATE runs SET finished=?,status=?,detail=? WHERE id=?',
            (utcnow(), 'DISCOVERY_OK' if broad else 'MONITOR_OK', f'{len(symbols)} observations; semantic gates require sourced evidence', run_id))
        db.commit()
        log.info('Run %s completed: %s observations; frozen rules evaluated conservatively', run_id, len(symbols))
    except Exception as exc:
        db.execute('UPDATE runs SET finished=?,status=?,detail=? WHERE id=?', (utcnow(), 'FAILED', str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__, run_id))
        db.commit()
        log.error('Run failed: %s', str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__)
        raise SystemExit(1) from None
    finally:
        db.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    run()
