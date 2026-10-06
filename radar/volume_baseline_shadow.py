"""Research-only 5-minute intraday volume baseline for SAG-30 SHADOW.

This does not authorize or modify any v0.3.3 FROZEN gate.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")

def init(db):
    db.execute("""
    CREATE TABLE IF NOT EXISTS shadow_volume_baseline(
      symbol TEXT NOT NULL,
      session_date TEXT NOT NULL,
      bucket_et TEXT NOT NULL,
      cumulative_volume REAL NOT NULL,
      source TEXT NOT NULL,
      PRIMARY KEY(symbol,session_date,bucket_et)
    )
    """)

def _bucket_et(ts):
    dt=datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(ET)
    minute=(dt.minute//5)*5
    return dt.replace(minute=minute,second=0,microsecond=0).strftime("%H:%M")

def ingest(db, bars_by_symbol, source="Alpaca IEX 5Min"):
    init(db)
    rows=0
    for symbol,bars in (bars_by_symbol or {}).items():
        per_session={}
        for bar in bars or []:
            ts=bar.get("t")
            vol=bar.get("v")
            if not ts or not isinstance(vol,(int,float)) or vol < 0:
                continue
            dt=datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(ET)
            session=dt.date().isoformat()
            bucket=_bucket_et(ts)
            per_session.setdefault(session,[]).append((dt,bucket,float(vol)))
        for session,items in per_session.items():
            total=0.0
            for _,bucket,vol in sorted(items):
                total += vol
                db.execute(
                    "INSERT OR REPLACE INTO shadow_volume_baseline(symbol,session_date,bucket_et,cumulative_volume,source) VALUES(?,?,?,?,?)",
                    (symbol,session,bucket,total,source)
                )
                rows += 1
    return rows

def fields(db, symbol, retrieval_ts, current_cumulative_volume=None):
    init(db)
    dt=datetime.fromisoformat(retrieval_ts).astimezone(ET)
    session=dt.date().isoformat()
    bucket=dt.replace(minute=(dt.minute//5)*5,second=0,microsecond=0).strftime("%H:%M")
    if current_cumulative_volume is None:
        current=db.execute(
            "SELECT cumulative_volume FROM shadow_volume_baseline WHERE symbol=? AND session_date=? AND bucket_et=?",
            (symbol,session,bucket)
        ).fetchone()
        current_cumulative_volume=float(current[0]) if current else None
    samples=[r[0] for r in db.execute(
        "SELECT cumulative_volume FROM shadow_volume_baseline WHERE symbol=? AND session_date<? AND bucket_et=? ORDER BY session_date DESC LIMIT 20",
        (symbol,session,bucket)
    ).fetchall()]
    samples=[float(x) for x in samples if isinstance(x,(int,float)) and x>0]
    med=None
    if samples:
        ordered=sorted(samples)
        n=len(ordered)
        med=ordered[n//2] if n%2 else (ordered[n//2-1]+ordered[n//2])/2
    ratio=None
    if med and isinstance(current_cumulative_volume,(int,float)) and current_cumulative_volume>=0:
        ratio=float(current_cumulative_volume)/med
    return {
      "shadow_bucket_et":bucket,
      "shadow_baseline_sample_count":len(samples),
      "shadow_baseline_median_cumulative_volume":med,
      "shadow_observed_volume_ratio":ratio,
      "shadow_baseline_method":"median cumulative 5-minute IEX volume at same ET bucket, prior sessions, max 20",
      "authoritative":False
    }

def historical_range(now, calendar_days=24):
    local=now.astimezone(ET)
    start=(local.date()-timedelta(days=calendar_days)).isoformat()+"T04:00:00-04:00"
    end=local.date().isoformat()+"T20:00:00-04:00"
    return start,end
