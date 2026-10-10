"""Immutable observed PAPER entry-review chronology, never a BUY or fill.

Capture only newly observed, current-session, fresh explicit review-stage rows.
Source/quote/retrieval/capture timestamps remain separate. SHADOW ONLY.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

UTC=timezone.utc
ET=ZoneInfo("America/New_York")
BUCHAREST=ZoneInfo("Europe/Bucharest")

def parse_ts(value):
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (TypeError,ValueError,AttributeError):
        return None

def zoned(dt):
    return {"utc":dt.isoformat(),"et":dt.astimezone(ET).isoformat(),
            "bucharest":dt.astimezone(BUCHAREST).isoformat()} if dt else None

def capture(db_path,state_dir,as_of=None):
    now=as_of or datetime.now(UTC)
    if now.tzinfo is None: raise ValueError("as_of must be timezone-aware")
    now=now.astimezone(UTC)
    session=now.astimezone(ET).date().isoformat()
    root=Path(state_dir)
    root.mkdir(parents=True,exist_ok=True)
    ledger=root/"shadow_first_paper_review.jsonl"
    report=root/"shadow_entry_timeline.json"
    previous=[json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []
    keys={(row["session"],row["symbol"]) for row in previous}
    db=sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    try:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='early_paper_extra_observations'").fetchone()
        new=[]
        skipped={"stale":0,"future":0,"wrong_session":0,"invalid_time":0}
        if exists:
            rows=db.execute("""SELECT run_id,session,symbol,discovery_ts,discovery_pct,
                quote_retrieved_ts,trade_ts,quote_ts,bid,ask,trade_price,spread_pct,
                screen_stage,blockers_json,feed
                FROM early_paper_extra_observations
                WHERE screen_stage='EARLY_PAPER_ENTRY_REVIEW'
                ORDER BY quote_retrieved_ts,run_id,symbol""").fetchall()
            for row in rows:
                key=(row["session"],row["symbol"])
                if key in keys: continue
                ts=parse_ts(row["quote_retrieved_ts"])
                if ts is None:
                    skipped["invalid_time"]+=1
                    continue
                if row["session"]!=session or ts.astimezone(ET).date().isoformat()!=session:
                    skipped["wrong_session"]+=1
                    continue
                if ts>now+timedelta(seconds=60):
                    skipped["future"]+=1
                    continue
                if now-ts>timedelta(minutes=15):
                    skipped["stale"]+=1
                    continue
                try: blockers=json.loads(row["blockers_json"] or "[]")
                except (ValueError,TypeError): blockers=["UNKNOWN_BLOCKERS"]
                event={
                    "session":row["session"],"symbol":row["symbol"],
                    "stage":"EARLY_PAPER_ENTRY_REVIEW","trading_action":"NONE",
                    "run_id":row["run_id"],"feed":row["feed"],
                    "retrieved_at":zoned(ts),"captured_at":zoned(now),
                    "source_trade_at":zoned(parse_ts(row["trade_ts"])),
                    "source_quote_at":zoned(parse_ts(row["quote_ts"])),
                    "discovery_at":zoned(parse_ts(row["discovery_ts"])),
                    "discovery_change_pct":row["discovery_pct"],
                    "observed_bid":row["bid"],"observed_ask":row["ask"],
                    "observed_trade_price":row["trade_price"],
                    "observed_spread_pct":row["spread_pct"],
                    "blockers":blockers,
                    "capture_lag_seconds":round((now-ts).total_seconds(),3),
                    "note":"Exact time of observed PAPER REVIEW stage, not actual BUY trigger or fill. IEX quote is not NBBO."
                }
                new.append(event)
                keys.add(key)
        if new:
            with ledger.open("a") as f:
                for event in new:f.write(json.dumps(event,sort_keys=True)+"\n")
        result={
            "status":"SHADOW_PAPER_REVIEW_TIMELINE_NOT_BUY",
            "capture_at":zoned(now),"market_session_et":session,
            "source_table_present":bool(exists),
            "new_reviews":len(new),"total_first_reviews":len(previous)+len(new),
            "new_events":new,"skipped":skipped,
            "actual_buy_trigger":"NOT_AVAILABLE_NO_PRODUCTION_BUY_SIGNAL",
            "warning":"Do not infer BUY from WATCH or PAPER ENTRY REVIEW. Missing event means NOT_OBSERVED, not proof that no signal was possible."
        }
        report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
        return result
    finally:db.close()

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--state-dir",required=True)
    a=p.parse_args()
    print(json.dumps(capture(a.db,a.state_dir),sort_keys=True))
