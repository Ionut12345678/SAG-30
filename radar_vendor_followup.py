"""Prospective read-only vendor-bar ledger. Never promotes vendor bars to validated trades."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

LEVELS=(15,20,30,50)

def timestamp(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("naive timestamp")
    return d.astimezone(timezone.utc)

def update(state,report):
    state=state if isinstance(state,dict) else {}
    ledger=state.setdefault("vendor_bar_ledger",{})
    now=timestamp(report["checked_at_utc"])
    changes=[]
    for obs in report.get("records",[]):
        if obs.get("status")!="RECENT_COMPLETED_BAR_VENDOR_UNVERIFIED":continue
        symbol=obs.get("symbol")
        try:
            bar=timestamp(obs["source_timestamp_utc"])
            price=float(obs["price"])
            reference=float(obs["reference_close"])
            volume=int(obs["bar_volume"])
            if not symbol or not 0<price or not 0<reference or volume<0 or bar>now:continue
            pct=100*(price/reference-1)
            if not 3<=pct<=10:continue
        except (KeyError,ValueError,TypeError):continue
        key=symbol+"|"+bar.astimezone(timezone.utc).date().isoformat()
        existing=ledger.get(key)
        if existing is None:
            ledger[key]={"symbol":symbol,"first_seen_utc":now.isoformat(),
                         "source_timestamp_utc":bar.isoformat(),"first_price":price,
                         "reference_close":reference,"first_volume":volume,
                         "last_source_timestamp_utc":bar.isoformat(),
                         "status":"VENDOR_UNVERIFIED","later_reported_milestones":[],
                         "later_observations":0}
            changes.append({"symbol":symbol,"event":"NEW_VENDOR_DISCOVERY","first_seen_utc":now.isoformat()})
        elif bar>timestamp(existing["last_source_timestamp_utc"]) and bar>timestamp(existing["source_timestamp_utc"]) and now>timestamp(existing["first_seen_utc"]):
            # A new bar is newer than the first bar and must not precede retrieval of first observation.
            if bar<=timestamp(existing["first_seen_utc"]):continue
            levels=set(existing["later_reported_milestones"])
            for level in LEVELS:
                if pct>=level:levels.add(level)
            existing["later_reported_milestones"]=sorted(levels)
            existing["last_source_timestamp_utc"]=bar.isoformat()
            existing["later_observations"]+=1
            changes.append({"symbol":symbol,"event":"FOLLOWUP_VENDOR_BAR","percent_vs_reference":round(pct,4),
                            "unverified_milestones":sorted(levels)})
    return state,{"checked_at_utc":now.isoformat(),"status":"VENDOR_RESEARCH_ONLY",
                  "validated_signals":0,"events":changes,"tracked_vendor_candidates":len(ledger)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",default="candidate-state.json")
    p.add_argument("--observations",default="yahoo-1m-shadow.json")
    p.add_argument("--out",default="prospective-vendor-ledger.json")
    a=p.parse_args()
    try:state=json.loads(Path(a.state).read_text())
    except (ValueError,OSError):state={}
    try:observations=json.loads(Path(a.observations).read_text())
    except (ValueError,OSError):observations={"checked_at_utc":datetime.now(timezone.utc).isoformat(),"records":[]}
    state,summary=update(state,observations)
    Path(a.state).write_text(json.dumps(state,indent=2,sort_keys=True)+"\n")
    Path(a.out).write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps({"tracked":summary["tracked_vendor_candidates"],"events":len(summary["events"]),"validated":0}))
if __name__=="__main__":main()
