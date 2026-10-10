"""Prospective SHADOW WATCH capture on each radar cycle; never backfill a WATCH.
Persist both immutable first WATCH and chronological source observations in radar-state.
NO BUY, NO TRADES; independent from v0.3.3 FROZEN.
"""
import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from radar.audit_leadtime_10m import evaluate

def parse_ts(s):
    try:
        t=datetime.fromisoformat(s.replace("Z","+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None

def read_jsonl(path):
    if not Path(path).exists(): return []
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]

def write_jsonl(path, rows):
    if not rows:return
    with Path(path).open("a") as f:
        for row in rows:f.write(json.dumps(row,sort_keys=True)+"\n")

def capture(db_path, state_dir, as_of=None):
    # Capture time is execution time, not source retrieval time.
    now=as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("as_of must be timezone aware")
    now=now.astimezone(timezone.utc)
    market_date=now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    freshness=timedelta(minutes=15)
    max_future_skew=timedelta(seconds=60)
    root=Path(state_dir);root.mkdir(parents=True,exist_ok=True)
    watch_path=root/"shadow_first_watch.jsonl"
    obs_path=root/"shadow_watch_observations.jsonl"
    status_path=root/"shadow_watch_status.json"
    watches=read_jsonl(watch_path)
    observations=read_jsonl(obs_path)
    watch_keys={(r["session"],r["symbol"]) for r in watches}
    obs_keys={(r["session"],r["symbol"],r["ts"]) for r in observations}
    db=sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    try:
        latest=db.execute("SELECT MAX(run_id) FROM scout_history").fetchone()[0]
        if latest is None:
            result={"status":"NO_SCOUT_HISTORY","new_watches":0,"new_observations":0,"capture_ts_utc":now.isoformat()}
        else:
            # Only current-run observations can generate a first WATCH.
            current=db.execute("""SELECT session,symbol,retrieval_ts,change_pct,run_id
              FROM scout_history WHERE run_id=? ORDER BY retrieval_ts,symbol""",(latest,)).fetchall()
            fresh=[]; new_watches=[]; stale_skipped=0; future_skipped=0; session_skipped=0
            for row in current:
                session,symbol,ts=row["session"],row["symbol"],row["retrieval_ts"]
                t=parse_ts(ts)
                try:p=float(row["change_pct"])
                except (ValueError,TypeError):continue
                if not t or not math.isfinite(p) or p<=-100:continue
                if session!=market_date or t.astimezone(ZoneInfo("America/New_York")).date().isoformat()!=market_date:
                    session_skipped+=1
                    continue
                if t>now+max_future_skew:
                    future_skipped+=1
                    continue
                if now-t>freshness:
                    stale_skipped+=1
                    continue
                key=(session,symbol,ts)
                if (session,symbol) in watch_keys:
                    if key not in obs_keys:
                        fresh.append({"session":session,"symbol":symbol,"ts":ts,
                                      "change_pct":p,"run_id":row["run_id"]})
                        obs_keys.add(key)
                    continue
                # Historical observations may provide momentum context, but are
                # NEVER written as earlier first WATCH events.
                history=db.execute("""SELECT retrieval_ts,change_pct FROM scout_history
                  WHERE session=? AND symbol=? AND retrieval_ts<=?
                  ORDER BY retrieval_ts DESC LIMIT 100""",(session,symbol,ts)).fetchall()
                series=[{"ts":h["retrieval_ts"],"change_pct":h["change_pct"]}
                        for h in reversed(history) if h["change_pct"] is not None]
                triggers=[]
                if p>=3:triggers.append("PRICE_3")
                for minutes,threshold,name in [(5,2,"MOMENTUM_5M_2"),(10,5,"MOMENTUM_10M_5")]:
                    prior=[float(h["change_pct"]) for h in series if parse_ts(h["ts"]) and
                           1 <= (t-parse_ts(h["ts"])).total_seconds() <= minutes*60 and
                           math.isfinite(float(h["change_pct"])) and float(h["change_pct"])>-100]
                    if prior and max(100*((100+p)/(100+v)-1) for v in prior)>=threshold:
                        triggers.append(name)
                if not triggers:continue
                new_watches.append({"session":session,"symbol":symbol,"ts":ts,
                   "captured_at_utc":now.isoformat(),
                   "retrieval_ts_utc":t.isoformat(),
                   "retrieval_ts_et":t.astimezone(ZoneInfo("America/New_York")).isoformat(),
                   "retrieval_ts_bucharest":t.astimezone(ZoneInfo("Europe/Bucharest")).isoformat(),
                   "change_pct":p,"run_id":row["run_id"],
                   "trigger_lanes":triggers,
                   "status":"WATCH_ONLY_NOT_BUY"})
                watch_keys.add((session,symbol))
                if key not in obs_keys:
                    fresh.append({"session":session,"symbol":symbol,"ts":ts,
                                  "change_pct":p,"run_id":row["run_id"]})
                    obs_keys.add(key)
            write_jsonl(obs_path,fresh)
            write_jsonl(watch_path,new_watches)
            # Evaluate from persisted source observations, not inferred maxima.
            grouped={}
            for row in observations+fresh:
                grouped.setdefault((row["session"],row["symbol"]),[]).append(
                    {"ts":row["ts"],"change_pct":row["change_pct"]})
            outcomes=[]
            for w in watches+new_watches:
                k=(w["session"],w["symbol"])
                series=grouped.get(k,[])
                # first SCOUT is not reconstructed from future samples.
                scout=db.execute("""SELECT retrieval_ts,change_pct FROM scout_history
                    WHERE session=? AND symbol=? AND retrieval_ts<=?
                    ORDER BY retrieval_ts ASC LIMIT 1""",(w["session"],w["symbol"],w["ts"])).fetchone()
                if scout is None:continue
                first={"ts":scout["retrieval_ts"],"change_pct":scout["change_pct"]}
                result=evaluate(first,series,{"ts":w["ts"],"change_pct":w["change_pct"]})
                outcomes.append({"session":w["session"],"symbol":w["symbol"],**result})
            result={"status":"SHADOW_PROSPECTIVE_ONLY_NOT_BUY",
                    "latest_run_id":latest,"new_watches":len(new_watches),
                    "new_observations":len(fresh),"total_watches":len(watches)+len(new_watches),
                    "capture_ts_utc":now.isoformat(),"market_session_et":market_date,
                    "stale_skipped":stale_skipped,"future_skipped":future_skipped,
                    "session_skipped":session_skipped,
                    "timestamp_basis":"retrieval_ts; not verified exchange source trade time",
                    "outcomes":outcomes,
                    "warning":"WATCH is recorded only when first observed in an active run; source gaps and unobserved onset remain UNVERIFIABLE. First scout from historic SQLite is context, not first WATCH. No fills or execution proof."}
    finally:db.close()
    status_path.write_text(json.dumps(result,indent=2,sort_keys=True))
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--state-dir",required=True)
    a=p.parse_args()
    print(json.dumps(capture(a.db,a.state_dir),sort_keys=True))
