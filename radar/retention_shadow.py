"""Independent 60-minute / 10-slot retention challenger. SHADOW ONLY / NOT BUY."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

def select(db, session, run_id, features, production_selected, now, minutes=60, cap=10):
    """Use prior scout selections only. Never rank on later price outcomes."""
    cutoff=(now-timedelta(minutes=minutes)).isoformat()
    rows=db.execute(
        "SELECT symbol,MAX(retrieval_ts) FROM scout_history "
        "WHERE session=? AND run_id<? AND selected=1 AND change_pct>=-10 AND change_pct<10 "
        "AND retrieval_ts>=? AND retrieval_ts<=? GROUP BY symbol",
        (session,run_id,cutoff,now.isoformat())
    ).fetchall()
    selected=set(production_selected)
    candidates=[]
    for symbol,ts in rows:
        f=features.get(symbol)
        if not f or symbol in selected:
            continue
        pct=f.get('change_pct')
        if not isinstance(pct,(int,float)) or not -10<=pct<10:
            continue
        # Exclude symbols already observed +30 in this session before this run.
        if db.execute(
            "SELECT 1 FROM scout_history WHERE session=? AND symbol=? AND run_id<? "
            "AND change_pct>=30 LIMIT 1",(session,symbol,run_id)
        ).fetchone():
            continue
        candidates.append((ts,symbol))
    candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return [symbol for _,symbol in candidates[:cap]]

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS retention_shadow_observations(
        run_id INTEGER NOT NULL,session TEXT NOT NULL,symbol TEXT NOT NULL,
        selected_ts TEXT NOT NULL,scout_pct REAL NOT NULL,
        observed_ts TEXT,source_ts TEXT,source_age_seconds REAL,
        deep_price REAL,feed TEXT NOT NULL,status TEXT NOT NULL,
        PRIMARY KEY(run_id,symbol))""")

def observe(db, run_id, session, features, production_selected, now, headers,
            feed, fetch, minutes=60, cap=10):
    """Separate snapshot request; never calls frozen evaluation or production alert bridge."""
    init(db)
    symbols=select(db,session,run_id,features,production_selected,now,minutes,cap)
    if not symbols:
        return {"status":"SHADOW_NO_EXTRA","selected":0,"valid":0}
    selected_ts={}
    for symbol in symbols:
        selected_ts[symbol]=db.execute(
            "SELECT MAX(retrieval_ts) FROM scout_history WHERE session=? AND run_id<? "
            "AND symbol=? AND selected=1 AND change_pct>=-10 AND change_pct<10",
            (session,run_id,symbol)
        ).fetchone()[0]
    try:
        snapshots,retrieved=fetch(
            'https://data.alpaca.markets/v2/stocks/snapshots?'+urlencode(
                {'symbols':','.join(symbols),'feed':feed}),headers)
    except Exception:
        # Research-only outage must not fail or change the production cycle.
        for symbol in symbols:
            db.execute("INSERT OR REPLACE INTO retention_shadow_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (run_id,session,symbol,selected_ts[symbol],features[symbol]['change_pct'],
                 None,None,None,None,feed,'SHADOW_FETCH_ERROR'))
        db.commit()
        return {"status":"SHADOW_FETCH_ERROR","selected":len(symbols),"valid":0}
    valid=0
    for symbol in symbols:
        snap=snapshots.get(symbol) or {}
        trade=snap.get('latestTrade') or {}
        source=trade.get('t')
        price=trade.get('p')
        age=None
        if source:
            try:
                age=(datetime.fromisoformat(retrieved.replace('Z','+00:00'))-
                     datetime.fromisoformat(source.replace('Z','+00:00'))).total_seconds()
            except (TypeError,ValueError):
                pass
        ok=(isinstance(price,(int,float)) and price>0 and
            age is not None and 0<=age<=900)
        status='SHADOW_FRESH_TRADE' if ok else 'SHADOW_DATA_GAP'
        valid+=int(ok)
        db.execute("INSERT OR REPLACE INTO retention_shadow_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id,session,symbol,selected_ts[symbol],features[symbol]['change_pct'],
             retrieved,source,age,float(price) if isinstance(price,(int,float)) else None,
             feed,status))
    db.commit()
    return {"status":"SHADOW_ONLY_NOT_BUY","selected":len(symbols),"valid":valid}
