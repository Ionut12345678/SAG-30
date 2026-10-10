"""Prospective PAPER BUY SIGNAL: simulated decision, never an order or fill.

Consumes explicit EARLY_PAPER_ENTRY_REVIEW evidence. Logs the first qualifying
observed signal per ET session and symbol; never backdates or invents a fill.
Independent from SAG-30 v0.3.3 FROZEN.
"""
import argparse
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
BUCHAREST=ZoneInfo("Europe/Bucharest")
UTC=timezone.utc

def parse_time(value):
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
        return t.astimezone(UTC) if t.tzinfo else None
    except (AttributeError,TypeError,ValueError):
        return None

def clocks(t):
    return {"utc":t.isoformat(),"new_york":t.astimezone(ET).isoformat(),
            "bucharest":t.astimezone(BUCHAREST).isoformat()} if t else None

def audit(db_path,state_dir,as_of=None):
    now=as_of or datetime.now(UTC)
    if now.tzinfo is None: raise ValueError("as_of must be timezone aware")
    now=now.astimezone(UTC)
    session=now.astimezone(ET).date().isoformat()
    root=Path(state_dir)
    root.mkdir(parents=True,exist_ok=True)
    ledger=root/"shadow_first_paper_buy_signal.jsonl"
    report=root/"shadow_paper_buy_audit.json"
    old=[json.loads(x) for x in ledger.read_text().splitlines() if x.strip()] if ledger.exists() else []
    seen={(r["session"],r["symbol"]) for r in old}
    db=sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    counts=Counter()
    new=[]
    try:
        exists=bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='early_paper_extra_observations'").fetchone())
        if exists:
            # Latest run is a prospective watermark: never replay historical successes.
            latest=db.execute("SELECT MAX(run_id) FROM early_paper_extra_observations").fetchone()[0]
            rows=db.execute("""SELECT * FROM early_paper_extra_observations
                 WHERE run_id=? ORDER BY quote_retrieved_ts,symbol""",(latest,)).fetchall() if latest is not None else []
            for row in rows:
                symbol=row["symbol"]
                counts["candidates"]+=1
                if (row["session"],symbol) in seen:
                    counts["already_signaled"]+=1
                    continue
                blockers=[]
                t=parse_time(row["quote_retrieved_ts"])
                trade=parse_time(row["trade_ts"])
                quote=parse_time(row["quote_ts"])
                discovery=parse_time(row["discovery_ts"])
                if row["session"]!=session or not t or t.astimezone(ET).date().isoformat()!=session:
                    blockers.append("WRONG_SESSION_OR_TIME")
                if not t or t>now+timedelta(seconds=60) or now-t>timedelta(minutes=15):
                    blockers.append("STALE_OR_FUTURE_CAPTURE")
                if row["screen_stage"]!="EARLY_PAPER_ENTRY_REVIEW":
                    blockers.append("NOT_PAPER_ENTRY_REVIEW")
                try:
                    source_blockers=json.loads(row["blockers_json"])
                    if not isinstance(source_blockers,list): raise ValueError("not list")
                except (TypeError,ValueError):
                    source_blockers=["INVALID_SOURCE_BLOCKERS"]
                blockers.extend(source_blockers)
                ask=row["ask"]
                if not isinstance(ask,(int,float)) or not math.isfinite(ask) or ask<=0:
                    blockers.append("INVALID_ASK")
                for name,source in (("TRADE",trade),("QUOTE",quote)):
                    if not t or not source or not 0<=(t-source).total_seconds()<=60:
                        blockers.append("STALE_OR_MISSING_"+name)
                if not discovery or not t or not 0<=(t-discovery).total_seconds()<=900:
                    blockers.append("INVALID_DISCOVERY_TTL")
                if blockers:
                    for b in set(blockers):counts["blocked_"+b]+=1
                    continue
                event={"session":session,"symbol":symbol,"stage":"PAPER_BUY_SIGNAL",
                    "execution":"NONE","order_allowed":False,"fill_confirmed":False,
                    "run_id":row["run_id"],"feed":row["feed"],
                    "signal_at":clocks(t),"captured_at":clocks(now),
                    "discovery_at":clocks(discovery),"source_trade_at":clocks(trade),
                    "source_quote_at":clocks(quote),
                    "indicative_ask":ask,"observed_bid":row["bid"],
                    "observed_trade_price":row["trade_price"],
                    "spread_pct":row["spread_pct"],
                    "capture_delay_seconds":round((now-t).total_seconds(),3),
                    "note":"Simulated signal based on observed IEX quote. No NBBO, no fill or profit inference."}
                new.append(event)
                seen.add((session,symbol))
                counts["paper_buy_signals"]+=1
        else:counts["missing_source_table"]+=1
        if new:
            with ledger.open("a") as f:
                for row in new:f.write(json.dumps(row,sort_keys=True)+"\n")
        result={"status":"PAPER_BUY_SHADOW_NO_ORDERS","session_et":session,
                "capture_at":clocks(now),"source_table_present":exists,
                "new_signals":len(new),"total_signals":len(old)+len(new),
                "funnel_counts":dict(sorted(counts.items())),"new_events":new,
                "warning":"No signal is not a live-trading failure; diagnose per-gate blockers. Signals are not executable BUY or filled trades."}
        report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
        return result
    finally:
        db.close()

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--state-dir",required=True)
    a=p.parse_args()
    print(json.dumps(audit(a.db,a.state_dir),sort_keys=True))
