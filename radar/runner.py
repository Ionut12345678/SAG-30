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
from .candidate_v034r2 import evaluate as evaluate_candidate_v034r2
from .scout import init as init_scout, momentum_and_update as scout_momentum_and_update, active_symbols as scout_active_symbols, record_promotions as scout_record_promotions, record_universe_history as scout_record_universe_history
from .multi_engine_shadow import evaluate as multi_engine_evaluate, record as multi_engine_record, watchpool_symbols as multi_engine_watchpool_symbols

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
    early=[s for s in symbols if isinstance(changes.get(s),(int,float)) and float(changes[s]) < 20]
    routes=[
        sorted(early,key=lambda s:(float(accelerations.get(s) or 0),s),reverse=True),
        sorted(early,key=lambda s:(float(volume_impulses.get(s) or 0),s),reverse=True),
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


def scout_discovery(db, run_id, universe, market_caps, headers, config, now):
    """Lightweight full-universe pass. No frozen/candidate semantic evaluation happens here."""
    init_scout(db)
    wall_started=time.monotonic()
    fetch_started=time.monotonic()
    local_hour=now.astimezone(ZoneInfo('America/New_York')).hour
    discovery_feed=config['feed']
    discovery_max_age=config['max_source_age_seconds']
    fallback_feed=config.get('discovery_fallback_feed')
    fallback_before=int(config.get('discovery_fallback_before_et_hour',0) or 0)
    if fallback_feed and local_hour < fallback_before:
        # Routing-only fallback for hours where the configured real-time venue is closed.
        # This never changes model evidence: deep observations still use config['feed'].
        discovery_feed=fallback_feed
        discovery_max_age=int(config.get('discovery_fallback_max_age_seconds',discovery_max_age))
    fetched=fetch_snapshot_batches(universe,headers,discovery_feed,config.get('snapshot_workers',8))
    fetch_seconds=time.monotonic()-fetch_started
    routing_snapshots={}
    routing_changes={}
    accelerations={}
    impulses={}
    features={}
    fallbacks=0
    eligible=0
    db.execute(
      "INSERT OR REPLACE INTO scout_runs(run_id,started_ts,universe_count) VALUES(?,?,?)",
      (run_id,now.isoformat(),len(universe))
    )
    for _,batch,started,result,retrieved in fetched:
        for symbol in batch:
            snapshot=result.get(symbol,{})
            route=routing_view(snapshot,retrieved,discovery_max_age)
            if not route:
                continue
            normalized,change,route_source=route
            price=float((normalized.get('latestTrade') or {}).get('p') or 0)
            volume=float((normalized.get('dailyBar') or {}).get('v') or 0)
            source_ts=(normalized.get('latestTrade') or {}).get('t')
            accel,fresh_volume,minutes=scout_momentum_and_update(
                db,symbol,retrieved,source_ts,price,change,volume,route_source
            )
            cap=float(market_caps.get(symbol) or 0)
            impulse=(fresh_volume*price/cap)/minutes if minutes and minutes>0 and cap>0 and price>0 else 0.0
            routing_snapshots[symbol]=normalized
            routing_changes[symbol]=change
            accelerations[symbol]=accel
            impulses[symbol]=impulse
            turnover=(volume*price/cap) if cap>0 and price>0 else 0.0
            features[symbol]={
              'retrieval_ts':retrieved,'change_pct':change,'acceleration':accel,'impulse':impulse,
              'turnover':turnover,'route_source':route_source
            }
            eligible += 1
            fallbacks += int(route_source=='minuteBar')
        db.commit()

    routed=route_shortlist(
        routing_snapshots,market_caps,routing_changes,config['shortlist_limit'],accelerations,impulses
    )
    session=now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    sticky=scout_active_symbols(db,session,config.get('sticky_active_limit',15))
    deep_limit=int(config.get('deep_shortlist_limit',45))
    base_selected=[]
    for symbol in list(sticky)+list(routed):
        if symbol not in base_selected:
            base_selected.append(symbol)
        if len(base_selected)>=deep_limit:
            break

    scores,high_recall,challenger_extras=multi_engine_evaluate(
        features,base_selected,
        extra_limit=config.get('multi_engine_extra_limit',20),
        watch_rank_limit=config.get('multi_engine_watch_rank_limit',80),
        min_change=config.get('multi_engine_min_change_pct',-10.0),
        max_change=config.get('multi_engine_max_change_pct',10.0),
    )
    retained=multi_engine_watchpool_symbols(
        db,session,
        limit=config.get('multi_engine_retained_limit',15),
        min_seen=config.get('multi_engine_min_seen',2),
    )
    # v0.4.10 RAPID-MOVER ROUTING RESCUE — routing only, prospective SHADOW / NOT BUY.
    # Cross-sectional dual-rank lane prevents a fast +1..<+10 mover from being crowded
    # out by the diversified shortlist. It does not alter any semantic/model gate.
    symbols=list(features)
    rank_change={s:i+1 for i,s in enumerate(sorted(symbols,key=lambda x:(float(features[x].get('change_pct') or 0),x),reverse=True))}
    rank_accel={s:i+1 for i,s in enumerate(sorted(symbols,key=lambda x:(float(features[x].get('acceleration') or 0),x),reverse=True))}
    rescue=[
      s for s in symbols
      if 1.0 <= float(features[s].get('change_pct') or 0) < 10.0
      and rank_change[s] <= 25 and rank_accel[s] <= 50
      and s not in base_selected
    ]
    rescue=sorted(rescue,key=lambda s:(rank_change[s]+rank_accel[s],rank_change[s],rank_accel[s],s))[:2]
    db.execute("""CREATE TABLE IF NOT EXISTS v0410_routing_rescue(
      session TEXT NOT NULL, run_id INTEGER NOT NULL, symbol TEXT NOT NULL, retrieval_ts TEXT NOT NULL,
      change_pct REAL NOT NULL, acceleration REAL NOT NULL, rank_change INTEGER NOT NULL,
      rank_acceleration INTEGER NOT NULL, status TEXT NOT NULL,
      PRIMARY KEY(session,run_id,symbol))""")
    for s in rescue:
        db.execute("INSERT OR REPLACE INTO v0410_routing_rescue VALUES(?,?,?,?,?,?,?,?,?)",
          (session,run_id,s,features[s]['retrieval_ts'],float(features[s]['change_pct']),
           float(features[s].get('acceleration') or 0),rank_change[s],rank_accel[s],'RAPID_MOVER_RESCUE_SHADOW'))

    # v0.4.12 EARLY-PREMARKET ROUTING SHADOW — external discovery is routing only.
    # It may promote a universe symbol even before delayed SIP has a fresh routing snapshot.
    # Deep/model evidence remains entirely on the existing entitled feed and frozen gates.
    external_premarket=[]
    # Carry today's early confirmed routes forward into the entitled IEX window.
    # This is shortlist retention only, not external price evidence or BUY.
    # Once the 08:00 ET transition arrives, keep the early routes eligible
    # for downstream checks instead of expiring them after 20 minutes.
    et=now.astimezone(ZoneInfo('America/New_York'))
    if (4, 0) <= (et.hour, et.minute) < (16, 0):
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v0412_premarket_route'").fetchone()
        if exists:
            cutoff=(now-timedelta(minutes=20)).isoformat() if et.hour < 8 else et.replace(hour=4,minute=0,second=0,microsecond=0).isoformat()
            rows=db.execute(
              "SELECT symbol,MIN(observed_ts) AS first_route FROM v0412_premarket_route "
              "WHERE session=? AND status='EARLY_PREMARKET_ROUTE_SHADOW' AND observed_ts>=? "
              "GROUP BY symbol ORDER BY first_route ASC,symbol ASC LIMIT 5",
              (session,cutoff)
            ).fetchall()
            external_premarket=[r[0] for r in rows]

    selected=list(base_selected)
    # External premarket and rapid-mover rescue get priority over retained/challenger extras.
    for symbol in list(external_premarket)+list(rescue)+list(retained)+list(challenger_extras):
        if symbol not in selected and (symbol in features or symbol in external_premarket):
            selected.append(symbol)
    multi_engine_record(db,run_id,session,features,scores,base_selected,challenger_extras)

    scout_record_universe_history(db,run_id,session,features,selected,sticky)
    scout_record_promotions(db,run_id,selected,features,sticky)
    db.execute(
      "UPDATE scout_runs SET finished_ts=?,eligible_count=?,selected_count=?,sticky_count=?,fetch_seconds=?,total_seconds=? WHERE run_id=?",
      (utcnow(),eligible,len(selected),sum(s in set(sticky) for s in selected),round(fetch_seconds,3),
       round(time.monotonic()-wall_started,3),run_id)
    )
    db.commit()
    top_accel=sorted(accelerations.items(),key=lambda x:x[1],reverse=True)[:8]
    top_impulse=sorted(impulses.items(),key=lambda x:x[1],reverse=True)[:8]
    early_selected=[(s,routing_changes.get(s),accelerations.get(s),impulses.get(s)) for s in selected if isinstance(routing_changes.get(s),(int,float)) and routing_changes[s] < 20]
    log.info(
      'SAG30_FAST_SCOUT feed=%s universe=%s eligible=%s selected=%s base_selected=%s external_premarket=%s challenger_extra=%s retained=%s high_recall=%s sticky=%s fetch_seconds=%.3f total_seconds=%.3f minute_fallbacks=%s top_accel=%s top_impulse=%s early_selected=%s',
      discovery_feed,len(universe),eligible,len(selected),len(base_selected),len(external_premarket),len(challenger_extras),len(retained),len(high_recall),
      sum(s in set(sticky) for s in selected),fetch_seconds,time.monotonic()-wall_started,
      fallbacks,top_accel,top_impulse,early_selected[:15]
    )
    return selected,features

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


def select_deep_feed(selected, headers, config, now):
    """Prefer real-time SIP when entitled; otherwise preserve configured evidence feed.

    Delayed SIP is never returned here and therefore can never become model evidence.
    """
    configured=config['feed']
    # Explicit entitlement configuration: do not repeatedly probe known-denied SIP.
    # This is feed selection only; never substitute delayed/public routing prices as evidence.
    if config.get('deep_preferred_feed_entitled') is False:
        log.info('SAG30_DEEP_FEED status=SKIPPED_NOT_ENTITLED fallback=%s', configured)
        return configured
    preferred=config.get('deep_preferred_feed')
    before=int(config.get('deep_preferred_before_et_hour',0) or 0)
    local_hour=now.astimezone(ZoneInfo('America/New_York')).hour
    if not selected or not preferred or local_hour >= before or preferred == configured:
        return configured
    probe=selected[0]
    try:
        url='https://data.alpaca.markets/v2/stocks/' + probe + '/snapshot?' + urlencode({'feed': preferred})
        request(url,headers)
        log.info('SAG30_DEEP_FEED preferred=%s status=AVAILABLE probe=%s',preferred,probe)
        return preferred
    except RuntimeError as exc:
        log.info('SAG30_DEEP_FEED preferred=%s status=UNAVAILABLE fallback=%s reason=%s',preferred,configured,str(exc))
        return configured

def prime_selected_after_discovery(db, run_id, selected, headers, config, evidence, feed=None):
    """Prospective second snapshot after shortlist selection and baseline backfill."""
    if not selected:
        return 0
    started=utcnow()
    evidence_feed=feed or config['feed']
    url='https://data.alpaca.markets/v2/stocks/snapshots?' + urlencode({'symbols': ','.join(selected), 'feed': evidence_feed})
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
        state_r2=evaluate_candidate_v034r2(db,observation_id,utcnow())
        states[state]=states.get(state,0)+1
        states["R2:"+state_r2]=states.get("R2:"+state_r2,0)+1
        ok += int(quality=='OK')
    db.commit()
    log.info('SAG30_POST_DISCOVERY_PRIME feed=%s selected=%s ok=%s candidate_states=%s',evidence_feed,len(selected),ok,sorted(states.items()))
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
        evidence_path = Path(config.get('evidence_file', 'config/evidence.json'))
        evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
        if not evidence_path.exists():
            log.warning('SAG30_SEMANTIC_EVIDENCE source=missing path=%s; undefined frozen gates remain WAIT/UNKNOWN', evidence_path)

        if broad:
            selected,_=scout_discovery(db,run_id,universe,market_caps,headers,config,now)
            if not selected:
                # Infrastructure/data failover only. Never claim full-universe discovery was healthy,
                # never backfill, and never change frozen/candidate model semantics.
                if not candidates:
                    raise ValueError('FAST SCOUT found no fresh routing-eligible snapshots and no existing shortlist is available')
                deep_feed=select_deep_feed(candidates,headers,config,now)
                refresh_shadow_volume_baseline(db,candidates,headers,deep_feed,now)
                deep_count=prime_selected_after_discovery(db,run_id,candidates,headers,config,evidence,deep_feed)
                if deep_count <= 0:
                    raise ValueError('FAST SCOUT data gap and fallback shortlist produced no observations')
                run_status='MONITOR_DATA_GAP'
                detail=f'DISCOVERY_DATA_GAP eligible=0/{len(universe)}; fallback existing shortlist {deep_count} observations; full-universe discovery unhealthy'
            else:
                marks=','.join('?' for _ in selected)
                db.execute('DELETE FROM candidates WHERE symbol NOT IN ('+marks+')',selected)
                for symbol in selected:
                    db.execute(
                      'INSERT INTO candidates VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET last_seen=excluded.last_seen,expires=excluded.expires',
                      (symbol,now.isoformat(),now.isoformat(),(now+timedelta(hours=24)).isoformat())
                    )
                deep_feed=select_deep_feed(selected,headers,config,now)
                refresh_shadow_volume_baseline(db,selected,headers,deep_feed,now)
                db.execute('DELETE FROM shadow_volume_baseline WHERE symbol NOT IN ('+marks+')',selected)
                deep_count=prime_selected_after_discovery(db,run_id,selected,headers,config,evidence,deep_feed)
                run_status='DISCOVERY_OK'
                detail=f'FAST_SCOUT {len(universe)} universe -> {deep_count} deep observations'
        else:
            if not candidates:
                raise ValueError('No shortlist candidates available for deep monitor')
            deep_feed=select_deep_feed(candidates,headers,config,now)
            refresh_shadow_volume_baseline(db,candidates,headers,deep_feed,now)
            deep_count=prime_selected_after_discovery(db,run_id,candidates,headers,config,evidence,deep_feed)
            run_status='MONITOR_OK'
            detail=f'DEEP_MONITOR {deep_count} observations'
        if deep_count <= 0:
            raise ValueError('No deep observations recorded after routing')
        valid_deep_count=db.execute(
            "SELECT COUNT(*) FROM observations WHERE run_id=? AND quality='OK'",(run_id,)
        ).fetchone()[0]
        if int(valid_deep_count or 0) == 0:
            local_hour=now.astimezone(ZoneInfo('America/New_York')).hour
            preferred=config.get('deep_preferred_feed')
            if local_hour < int(config.get('deep_preferred_before_et_hour',0) or 0) and deep_feed == config['feed'] and preferred:
                run_status='PREMARKET_ROUTING_ONLY'
                detail=detail + '; routing active; entitled premarket real-time evidence feed unavailable, frozen model evidence remains blocked'
            else:
                run_status='MONITOR_DATA_GAP'
                detail=detail + '; deep real-time feed has 0 valid observations'
        db.execute('UPDATE runs SET finished=?,status=?,detail=? WHERE id=?',
            (utcnow(),run_status,detail,run_id))
        db.commit()
        log.info('Run %s completed: %s',run_id,detail)
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
