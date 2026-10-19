"""Persist read-only, unverified Nasdaq screening follow-ups across separate CI runs.

This is not a live quote/BUY system. Both 'entry' and follow-up are website
snapshots captured at retrieval time, not independently timed exchange prints.
"""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from radar_discovery import fetch_payload, get_rows, percent

LEVELS = (15, 20, 30, 50)
MAX_SYMBOLS = 2500
MAX_SESSIONS = 10

def parse_price(value):
    if isinstance(value,bool): return None
    s=str(value or "").strip().replace("$","").replace(",","")
    try:
        n=float(s)
        return n if math.isfinite(n) and n>0 else None
    except ValueError: return None

def valid_state(value):
    if not isinstance(value,dict) or value.get("version")!=1 or not isinstance(value.get("sessions"),dict):
        return {"version":1,"sessions":{}}
    return value

def merge_scan(state, payload, at):
    """Return a copied state + auditable report; source failure never deletes history."""
    state=json.loads(json.dumps(valid_state(state)))
    now=at.astimezone(timezone.utc).isoformat()
    session=at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    result={"scan_received_utc":now,"session":session,"status":"NO_DATA",
      "source":"Nasdaq public screener","quality":"UNVERIFIED_WEBSITE_SNAPSHOT",
      "quote_timestamp_verified":False,"real_time_verified":False,"buy_enabled":False,
      "valid_first_watch_signals":0,"new_candidates":0,"tracked_symbols":0,
      "new_reported_milestones":0,"sample":[],"previous_state_loaded":bool(state["sessions"])}
    try:
        rows,total=get_rows(payload)
        if not rows:
            result["status"]="EMPTY_SOURCE"
            return state,result
        report_rows={}
        for row in rows:
            if not isinstance(row,dict): continue
            symbol=str(row.get("symbol") or "").strip().upper()
            if not symbol or len(symbol)>12:continue
            change=percent(row.get("pctchange"))
            if change is None:continue
            # A symbol may occur twice: keep first occurrence; do not cherry-pick.
            if symbol not in report_rows:
                report_rows[symbol]={"pct":change,"price":parse_price(row.get("lastsale"))}
        session_map=state["sessions"].setdefault(session,{})
        if not isinstance(session_map,dict):session_map={};state["sessions"][session]=session_map
        new_symbols=[]
        new_milestones=0
        for sym,obs in sorted(report_rows.items()):
            change=obs["pct"]
            existing=session_map.get(sym)
            if existing is None:
                if not (5<=change<=10): continue
                if len(session_map)>=MAX_SYMBOLS: continue
                existing={"first_seen_utc":now,"first_reported_pct":change,
                  "first_last_sale":obs["price"],"highest_later_reported_pct":None,
                  "first_source_quote_time":None,"first_classification":"UNVERIFIED_DISCOVERY_ONLY",
                  "milestones_reported":[],"followup_count":0}
                session_map[sym]=existing
                new_symbols.append(sym)
                continue
            first=existing.get("first_seen_utc")
            if not isinstance(first,str) or first>=now:continue
            existing["followup_count"]=int(existing.get("followup_count") or 0)+1
            previous=existing.get("highest_later_reported_pct")
            existing["highest_later_reported_pct"]=max(change,previous) if isinstance(previous,(float,int)) else change
            existing["last_seen_utc"]=now
            existing["last_reported_pct"]=change
            existing["last_last_sale"]=obs["price"]
            levels=set(existing.get("milestones_reported",[]))
            for level in LEVELS:
                if change>=level and level not in levels:
                    levels.add(level);new_milestones+=1
            existing["milestones_reported"]=sorted(levels)
        # Cap retained sessions and keep most recent by Eastern date.
        for old in sorted(state["sessions"])[:-MAX_SESSIONS]:state["sessions"].pop(old,None)
        result.update(status="UNVERIFIED_SCREENING_OBSERVED",
          received_rows=len(rows),parsed_rows=len(report_rows),reported_universe_size=total,
          partial_universe=bool(isinstance(total,int) and total>len(rows)),
          new_candidates=len(new_symbols),tracked_symbols=len(session_map),
          new_reported_milestones=new_milestones,
          sample=[{"symbol":s,"first_reported_pct":session_map[s]["first_reported_pct"],
             "first_seen_utc":session_map[s]["first_seen_utc"]} for s in new_symbols[:40]])
    except (TypeError,ValueError,KeyError,AttributeError):
        result["status"]="SOURCE_SCHEMA_ERROR"
    return state,result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",default="candidate-state.json")
    ap.add_argument("--out",default="candidate-followup.json")
    args=ap.parse_args()
    state_path=Path(args.state)
    try:
        state=valid_state(json.loads(state_path.read_text())) if state_path.exists() else valid_state(None)
    except (ValueError,OSError):
        state=valid_state(None)
    try:
        payload=fetch_payload()
        state,report=merge_scan(state,payload,datetime.now(timezone.utc))
    except Exception as e:
        report={"status":"SOURCE_ERROR","error_type":type(e).__name__,
          "quality":"UNVERIFIED_WEBSITE_SNAPSHOT","valid_first_watch_signals":0,
          "buy_enabled":False,"new_candidates":0}
    # Only write a state snapshot when fetch + schema processed successfully.
    if report["status"]=="UNVERIFIED_SCREENING_OBSERVED":
        state_path.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    Path(args.out).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:report.get(k) for k in ["status","new_candidates","tracked_symbols",
        "new_reported_milestones","valid_first_watch_signals"]}))

if __name__=="__main__":main()
