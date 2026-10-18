"""Radar Nou v0.5: timestamp-safe, offline shadow observations, no orders."""
import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LEVELS = (15, 20, 30, 50)
MAX_SOURCE_AGE_SECONDS = 120
HORIZON_SECONDS = 4 * 3600

def stamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)

def connect(path):
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS observations(
        symbol TEXT, session TEXT, received TEXT, source TEXT, price REAL, reference REAL,
        PRIMARY KEY(symbol, session, source));
    CREATE TABLE IF NOT EXISTS alerts(
        symbol TEXT, session TEXT, first_seen TEXT, first_source TEXT, first_price REAL,
        reference REAL, PRIMARY KEY(symbol, session));
    CREATE TABLE IF NOT EXISTS milestones(
        symbol TEXT, session TEXT, level INTEGER, observed TEXT, source TEXT, price REAL,
        PRIMARY KEY(symbol, session, level));
    CREATE TABLE IF NOT EXISTS scans(
        id TEXT PRIMARY KEY, started TEXT, status TEXT, input_count INTEGER,
        valid_count INTEGER);
    CREATE TABLE IF NOT EXISTS rejected(symbol TEXT, reason TEXT, at TEXT);
    """)
    return c

def ingest(c, row):
    symbol = str(row["symbol"]).strip().upper()
    session = str(row["session"])
    received = stamp(row["observed_at"])
    source = stamp(row["source_ts"])
    price = float(row["price"])
    reference = float(row["previous_close"])
    if not symbol or not math.isfinite(price) or not math.isfinite(reference) or min(price,reference)<=0:
        raise ValueError("invalid price/symbol")
    age=(received-source).total_seconds()
    if age<0 or age>MAX_SOURCE_AGE_SECONDS:
        with c:
            c.execute("INSERT INTO rejected VALUES(?,?,?)",(symbol,"FUTURE_TS" if age<0 else "STALE_TS",received.isoformat()))
        return "REJECTED"
    if session!=source.date().isoformat():
        with c:c.execute("INSERT INTO rejected VALUES(?,?,?)",(symbol,"WRONG_SESSION",received.isoformat()))
        return "REJECTED"
    baseline=c.execute("SELECT reference FROM observations WHERE symbol=? AND session=? LIMIT 1",(symbol,session)).fetchone()
    if baseline and not math.isclose(baseline[0],reference,rel_tol=1e-9,abs_tol=1e-9):
        with c:c.execute("INSERT INTO rejected VALUES(?,?,?)",(symbol,"CHANGED_REFERENCE",received.isoformat()))
        return "REJECTED"
    last=c.execute("SELECT MAX(source) FROM observations WHERE symbol=? AND session=?",(symbol,session)).fetchone()[0]
    if last and source.isoformat()<=last:
        return "DUPLICATE_OR_OUT_OF_ORDER"
    with c:
        c.execute("INSERT INTO observations VALUES(?,?,?,?,?,?)",(symbol,session,received.isoformat(),source.isoformat(),price,reference))
        first=c.execute("SELECT first_seen,first_source,first_price,reference FROM alerts WHERE symbol=? AND session=?",(symbol,session)).fetchone()
        pct=100*(price/reference-1)
        if first is None:
            if 5<=pct<=10:
                c.execute("INSERT INTO alerts VALUES(?,?,?,?,?,?)",(symbol,session,received.isoformat(),source.isoformat(),price,reference))
                return "FIRST_WATCH"
            return "OBSERVED_NO_SIGNAL"
        first_seen,first_source,entry,baseline=first
        if received.isoformat()<=first_seen or source.isoformat()<=first_seen or source.isoformat()<=first_source:
            return "NOT_POST_ALERT"
        if (source-stamp(first_seen)).total_seconds()>HORIZON_SECONDS:
            return "AFTER_HORIZON"
        for level in LEVELS:
            if 100*(price/baseline-1)>=level:
                c.execute("INSERT OR IGNORE INTO milestones VALUES(?,?,?,?,?,?)",(symbol,session,level,received.isoformat(),source.isoformat(),price))
        return "FOLLOW_UP"

def report(c):
    items=[]
    for symbol,session,first,source,entry,ref in c.execute("SELECT * FROM alerts ORDER BY first_seen").fetchall():
        rows=c.execute("SELECT price,source FROM observations WHERE symbol=? AND session=? AND received>? AND source>? ORDER BY source",(symbol,session,first,first)).fetchall()
        prices=[price for price,when in rows if (stamp(when)-stamp(first)).total_seconds()<=HORIZON_SECONDS]
        maximum=max(prices,default=None)
        levels=[r[0] for r in c.execute("SELECT level FROM milestones WHERE symbol=? AND session=? ORDER BY level",(symbol,session))]
        items.append({"symbol":symbol,"session":session,"first_seen":first,"source_ts":source,"first_price":entry,
          "previous_close":ref,"first_pct":round(100*(entry/ref-1),4),"post_observations":len(prices),
          "max_post_price":maximum,"max_gain_from_entry_pct":round(100*(maximum/entry-1),4) if maximum is not None else None,
          "milestones_vs_previous_close":levels,"result":"OBSERVED" if prices else "UNKNOWN_NO_FOLLOW_UP"})
    return {"mode":"SHADOW_ONLY","buy":False,"orders_enabled":False,"sessions_validated":0,
      "observations":c.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
      "first_watches":len(items),"no_follow_up":sum(i["post_observations"]==0 for i in items),
      "false_positive_rate":None,"market_wide_coverage":None,
      "rejected":dict(c.execute("SELECT reason, COUNT(*) FROM rejected GROUP BY reason")),
      "scans":dict(c.execute("SELECT status,COUNT(*) FROM scans GROUP BY status")),
      "signals":items}

def scan(c,payload,now=None):
    now=now or datetime.now(timezone.utc)
    seen=now.astimezone(timezone.utc).isoformat()
    if not isinstance(payload,dict) or not payload.get("provider") or not payload.get("session") or not isinstance(payload.get("quotes"),list):
        raise ValueError("invalid input")
    valid=0
    seen_symbols=set()
    outcomes={}
    for quote in payload["quotes"]:
        try:
            symbol=str(quote["symbol"]).upper()
            if symbol in seen_symbols: outcome="DUPLICATE_IN_BATCH"
            else:
                seen_symbols.add(symbol)
                outcome=ingest(c,dict(quote,session=payload["session"],observed_at=seen))
        except (TypeError,ValueError,KeyError,OverflowError):
            outcome="INVALID_ROW"
        outcomes[outcome]=outcomes.get(outcome,0)+1
        if outcome in ("FIRST_WATCH","OBSERVED_NO_SIGNAL","NOT_POST_ALERT","AFTER_HORIZON","FOLLOW_UP"):
            valid+=1
    status="OBSERVED" if valid and valid==len(seen_symbols) else ("PARTIAL_OBSERVED" if valid else ("NO_NEW_TICKS" if outcomes.get("DUPLICATE_OR_OUT_OF_ORDER") else "DATA_GAP"))
    with c:c.execute("INSERT INTO scans VALUES(?,?,?,?,?)",(seen,seen,status,len(seen_symbols),valid))
    return {"status":status,"provider":payload["provider"],"input_rows":len(payload["quotes"]),"unique_symbols":len(seen_symbols),
      "valid_observations":valid,"outcomes":outcomes,"report":report(c)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="radar.sqlite")
    p.add_argument("--feed")
    p.add_argument("--output",default="radar-report.json")
    a=p.parse_args()
    c=connect(a.db)
    result=scan(c,json.loads(Path(a.feed).read_text())) if a.feed else {"status":"NO_FEED","report":report(c)}
    Path(a.output).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"first_watches":result["report"]["first_watches"]}))
    c.close()

if __name__=="__main__":main()
