"""SAG-30 v0.4 FAST-PATH SHADOW.

Research-only one-minute challenger layered on top of the existing 5-minute discovery.
It never emits BUY and never changes v0.3.3 FROZEN/r2 gates.

Paths:
- EVENT: catalyst headline + positive early price reaction
- FLOW: sub-10% positive move + positive acceleration/impulse persistence

States:
DISCOVERED -> PREARM_EVENT/PREARM_FLOW -> TRIGGER_SHADOW
Any move >=20% is LATE_SHADOW for this challenger.
"""
import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
DATA="https://data.alpaca.markets"

CATALYSTS={
 "ANTI_DILUTION_BUYBACK":("buyback","repurchase","at-the-market","atm","suspend"),
 "MNA":("merger","acquisition","acquire","strategic combination","business combination"),
 "CONTRACT":("contract","agreement","award","order","purchase order","customer"),
 "FDA_CLINICAL":("fda","clinical","trial","phase 1","phase 2","phase 3","topline"),
 "GOV_DEFENSE":("department of defense","dod","government","federal","army","navy","air force","grant"),
 "EARNINGS":("earnings","results","revenue","guidance"),
 "PATENT_TECH":("patent","technology","platform","artificial intelligence","blockchain"),
}

def req(path, params, headers):
    url=DATA+path+"?"+urlencode(params)
    with urlopen(Request(url,headers=headers),timeout=30) as r:
        return json.loads(r.read())

def load_universe(path):
    with open(path,newline="") as f:
        return {r["symbol"].strip().upper() for r in csv.DictReader(f) if r.get("symbol")}

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS fast_path_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session TEXT NOT NULL,
      symbol TEXT NOT NULL,
      retrieval_ts TEXT NOT NULL,
      source TEXT NOT NULL,
      state TEXT NOT NULL,
      change_pct REAL,
      acceleration REAL,
      impulse REAL,
      evidence TEXT,
      catalyst TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_fast_path_symbol_session
      ON fast_path_events(session,symbol,id);

    CREATE TABLE IF NOT EXISTS fast_path_state(
      session TEXT NOT NULL,
      symbol TEXT NOT NULL,
      first_seen_ts TEXT NOT NULL,
      last_seen_ts TEXT NOT NULL,
      seen_count INTEGER NOT NULL,
      positive_flow_count INTEGER NOT NULL,
      peak_change_pct REAL,
      last_change_pct REAL,
      last_volume REAL,
      last_price REAL,
      last_source_ts TEXT,
      last_state TEXT NOT NULL,
      last_catalyst TEXT,
      PRIMARY KEY(session,symbol)
    );
    """)
    cols={r[1] for r in db.execute("PRAGMA table_info(fast_path_events)")}
    for name,typ in [
      ("bid","REAL"),("ask","REAL"),("spread_pct","REAL"),
      ("minute_bar_present","INTEGER"),("consecutive_minute_bar","INTEGER")
    ]:
        if name not in cols:
            db.execute(f"ALTER TABLE fast_path_events ADD COLUMN {name} {typ}")

def candidate_pool(db, session, limit=80):
    pool=[]
    seen=set()
    for q,args in [
      ("SELECT symbol FROM multi_engine_watchpool WHERE session=? ORDER BY peak_score DESC,last_seen_ts DESC LIMIT ?",(session,limit)),
      ("SELECT symbol FROM candidates ORDER BY symbol",( )),
    ]:
        try:
            rows=db.execute(q,args).fetchall()
        except sqlite3.OperationalError:
            rows=[]
        for (s,) in rows:
            if s not in seen:
                pool.append(s);seen.add(s)
    return pool[:max(limit,120)]

def classify_news(items):
    by_symbol={}
    for n in items:
        text=((n.get("headline") or "")+" "+(n.get("summary") or "")).lower()
        cats=[cat for cat,words in CATALYSTS.items() if any(w in text for w in words)]
        if not cats: continue
        for s in n.get("symbols") or []:
            by_symbol.setdefault(s.upper(),set()).update(cats)
    return {s:sorted(v) for s,v in by_symbol.items()}

def recent_news(headers, now, minutes=3):
    start=(now-timedelta(minutes=minutes)).isoformat()
    try:
        payload=req("/v1beta1/news",{"start":start,"sort":"desc","limit":100,"include_content":"false"},headers)
        return payload.get("news") or []
    except Exception:
        return []

def snapshots(symbols, headers, feed):
    out={}
    for off in range(0,len(symbols),100):
        batch=symbols[off:off+100]
        if not batch: continue
        payload=req("/v2/stocks/snapshots",{"symbols":",".join(batch),"feed":feed},headers)
        out.update(payload)
    return out

def view(snap):
    """Use completed 1-minute bars for FAST-PATH flow evidence.

    The prior implementation used dailyBar cumulative volume, which can remain
    unchanged in extended hours and made every one-minute flow impulse zero.
    Minute-bar timestamp + volume are the correct evidence unit for this loop.
    """
    prev=(snap.get("prevDailyBar") or {}).get("c")
    if not isinstance(prev,(int,float)) or prev<=0:
        return None
    mb=snap.get("minuteBar") or {}
    price=mb.get("c")
    high=mb.get("h")
    ts=mb.get("t")
    vol=mb.get("v")
    quote=snap.get("latestQuote") or {}
    bid=quote.get("bp"); ask=quote.get("ap")
    spread_pct=None
    if isinstance(bid,(int,float)) and isinstance(ask,(int,float)) and bid>0 and ask>=bid:
        mid=(float(ask)+float(bid))/2.0
        if mid>0:
            spread_pct=(float(ask)-float(bid))/mid*100.0
    if isinstance(price,(int,float)) and price>0 and ts and isinstance(vol,(int,float)):
        pct=float((price/prev-1)*100)
        high_pct=float((high/prev-1)*100) if isinstance(high,(int,float)) and high>0 else pct
        return float(price),pct,float(vol),ts,bid,ask,spread_pct,1,high_pct
    # Price-only fallback is allowed for EVENT observation, but cannot create
    # FLOW persistence because volume is zero and source timestamp is trade time.
    trade=snap.get("latestTrade") or {}
    price=trade.get("p")
    ts=trade.get("t")
    if not isinstance(price,(int,float)) or price<=0 or not ts:
        return None
    pct=float((price/prev-1)*100)
    return float(price),pct,0.0,ts,bid,ask,spread_pct,0,pct

def evaluate_one(db, session, symbol, source, catalyst, obs, now):
    price,pct,vol,source_ts,bid,ask,spread_pct,minute_bar_present,bar_high_pct=obs
    row=db.execute(
      "SELECT first_seen_ts,last_seen_ts,seen_count,positive_flow_count,peak_change_pct,last_change_pct,last_volume,last_price,last_source_ts,last_state,last_catalyst "
      "FROM fast_path_state WHERE session=? AND symbol=?",(session,symbol)
    ).fetchone()
    accel=0.0; impulse=0.0; pos_count=0
    first=now.isoformat()
    new_source=True
    consecutive_minute_bar=0
    if row:
        first=row[0]
        pos_count=int(row[3] or 0)
        prior_source_ts=row[8]
        new_source=(source_ts != prior_source_ts)
        try:
            prior_dt=datetime.fromisoformat(prior_source_ts.replace("Z","+00:00")) if prior_source_ts else datetime.fromisoformat(row[1])
            current_dt=datetime.fromisoformat(source_ts.replace("Z","+00:00"))
            dt=(current_dt-prior_dt).total_seconds()/60.0
        except Exception:
            dt=0
        if new_source and dt>0:
            accel=(pct-float(row[5] or 0))/dt
            # minuteBar volume is already the fresh volume for the new interval.
            impulse=max(0.0,vol)/dt
            consecutive_minute_bar=int(minute_bar_present and 0.5 <= dt <= 1.5)
    positive=(new_source and 0 < pct < 10 and accel>0 and impulse>0)
    if new_source:
        pos_count=pos_count+1 if positive else 0

    state="DISCOVERED"; evidence=[]
    if pct>=20:
        state="LATE_SHADOW";evidence.append("price>=20")
    elif catalyst and 0 < pct < 10 and accel>=0:
        state="PREARM_EVENT";evidence.extend(["classified catalyst","positive sub10 reaction"])
        if row and float(row[5] or 0) < pct and pct>=2:
            state="TRIGGER_SHADOW";evidence.append("rising price after event prearm")
    elif 0 < pct < 10 and pos_count>=2:
        state="PREARM_FLOW";evidence.extend(["sub10","positive acceleration","positive fresh volume","persistence>=2"])
        if row and pct>=2 and pct>float(row[5] or 0):
            state="TRIGGER_SHADOW";evidence.append("continued rising price")
    elif 0 < pct < 10 and positive:
        state="DISCOVERED";evidence.append("first positive flow observation")

    peak=max(pct,float(row[4])) if row and row[4] is not None else pct
    cats=",".join(catalyst or [])
    db.execute(
      "INSERT INTO fast_path_events(session,symbol,retrieval_ts,source,state,change_pct,acceleration,impulse,evidence,catalyst,bid,ask,spread_pct,minute_bar_present,consecutive_minute_bar,bar_high_pct,observed_volume) "
      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
      (session,symbol,now.isoformat(),source,state,pct,accel,impulse,"; ".join(evidence),cats,
       float(bid) if isinstance(bid,(int,float)) else None,
       float(ask) if isinstance(ask,(int,float)) else None,
       float(spread_pct) if isinstance(spread_pct,(int,float)) else None,
       int(minute_bar_present),int(consecutive_minute_bar),float(bar_high_pct),float(vol))
    )
    db.execute(
      "INSERT INTO fast_path_state(session,symbol,first_seen_ts,last_seen_ts,seen_count,positive_flow_count,peak_change_pct,last_change_pct,last_volume,last_price,last_source_ts,last_state,last_catalyst) "
      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
      "ON CONFLICT(session,symbol) DO UPDATE SET last_seen_ts=excluded.last_seen_ts,seen_count=fast_path_state.seen_count+1,"
      "positive_flow_count=excluded.positive_flow_count,peak_change_pct=MAX(fast_path_state.peak_change_pct,excluded.peak_change_pct),"
      "last_change_pct=excluded.last_change_pct,last_volume=excluded.last_volume,last_price=excluded.last_price,last_source_ts=excluded.last_source_ts,"
      "last_state=excluded.last_state,last_catalyst=CASE WHEN excluded.last_catalyst<>'' THEN excluded.last_catalyst ELSE fast_path_state.last_catalyst END",
      (session,symbol,first,now.isoformat(),1,pos_count,peak,pct,vol,price,source_ts,state,cats)
    )
    return {"symbol":symbol,"state":state,"change_pct":pct,"acceleration":accel,"impulse":impulse,
            "source":source,"catalyst":catalyst or [],"bid":bid,"ask":ask,"spread_pct":spread_pct,
            "minute_bar_present":bool(minute_bar_present),"consecutive_minute_bar":bool(consecutive_minute_bar),
            "bar_high_pct":bar_high_pct,"observed_volume":vol}

def build_report(db, session, out):
    states={}
    for state,n in db.execute("SELECT last_state,COUNT(*) FROM fast_path_state WHERE session=? GROUP BY last_state",(session,)):
        states[state]=n
    rows=[]
    for r in db.execute(
      "SELECT symbol,last_state,last_change_pct,peak_change_pct,seen_count,positive_flow_count,last_catalyst,last_seen_ts "
      "FROM fast_path_state WHERE session=? ORDER BY CASE last_state WHEN 'TRIGGER_SHADOW' THEN 0 WHEN 'PREARM_EVENT' THEN 1 WHEN 'PREARM_FLOW' THEN 2 ELSE 3 END, peak_change_pct DESC LIMIT 100",
      (session,)
    ):
        rows.append({"symbol":r[0],"state":r[1],"change_pct":r[2],"peak_change_pct":r[3],"seen_count":r[4],"positive_flow_count":r[5],"catalyst":r[6],"last_seen_ts":r[7]})
    coverage=db.execute(
      "SELECT COUNT(*),SUM(CASE WHEN minute_bar_present=1 THEN 1 ELSE 0 END),"
      "SUM(CASE WHEN consecutive_minute_bar=1 THEN 1 ELSE 0 END) FROM fast_path_events WHERE session=?",(session,)
    ).fetchone()
    prearm_exec=db.execute(
      "SELECT COUNT(*),SUM(CASE WHEN ask IS NOT NULL THEN 1 ELSE 0 END),"
      "AVG(CASE WHEN state IN ('PREARM_EVENT','PREARM_FLOW','TRIGGER_SHADOW') THEN spread_pct END) "
      "FROM fast_path_events WHERE session=?",(session,)
    ).fetchone()
    total=int(coverage[0] or 0)
    minute_present=int(coverage[1] or 0)
    consecutive=int(coverage[2] or 0)
    payload={
      "status":"FAST_PATH_V0.4.1_CALIBRATION_SHADOW","authoritative":False,"buy":False,
      "session":session,"generated_at":datetime.now(timezone.utc).isoformat(),
      "states":states,"candidates":rows,
      "data_quality":{
        "observations":total,
        "minute_bar_present_rate":(minute_present/total if total else None),
        "consecutive_1m_bar_rate":(consecutive/total if total else None),
        "ask_available_count":int(prearm_exec[1] or 0)
      },
      "execution":{
        "avg_prearm_trigger_spread_pct":prearm_exec[2]
      },
      "note":"Research-only. v0.3.3 FROZEN and r2 gates unchanged. TRIGGER_SHADOW is not BUY."
    }
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    Path(out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="state/radar.sqlite3")
    p.add_argument("--config",default="config/radar.json")
    p.add_argument("--out",default="state/fast_path_report.json")
    p.add_argument("--watch-limit",type=int,default=80)
    p.add_argument("--news-minutes",type=int,default=3)
    a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text())
    headers={"APCA-API-KEY-ID":os.environ["ALPACA_API_KEY"],"APCA-API-SECRET-KEY":os.environ["ALPACA_SECRET_KEY"]}
    now=datetime.now(timezone.utc)
    session=now.astimezone(ET).date().isoformat()
    db=sqlite3.connect(a.db)
    init(db)
    universe=load_universe(cfg["universe_file"])
    pool=candidate_pool(db,session,a.watch_limit)
    news=classify_news(recent_news(headers,now,a.news_minutes))
    event_syms=[s for s in news if s in universe]
    symbols=[]
    for s in pool+event_syms:
        if s not in symbols: symbols.append(s)
    snaps=snapshots(symbols,headers,cfg.get("feed","iex")) if symbols else {}
    results=[]
    for s in symbols:
        obs=view(snaps.get(s,{}) )
        if not obs: continue
        source="EVENT" if s in news else "WATCHPOOL"
        results.append(evaluate_one(db,session,s,source,news.get(s),obs,now))
    db.commit()
    build_report(db,session,a.out)
    triggers=[r for r in results if r["state"]=="TRIGGER_SHADOW"]
    print(json.dumps({"observed":len(results),"event_interrupts":len(event_syms),"triggers":triggers},sort_keys=True))

if __name__=="__main__":
    main()
