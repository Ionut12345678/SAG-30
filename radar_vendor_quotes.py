"""Read-only vendor-timestamped quote ledger; not exchange-verified or tradable."""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

THRESHOLDS=(15,20,30,50)
def reconcile(state,feed):
    state=json.loads(json.dumps(state)) if isinstance(state,dict) else {}
    tracked=state.setdefault("symbols",{})
    provider=feed.get("provider","Yahoo public chart (unofficial)") if isinstance(feed,dict) else "Unknown"
    output={"status":"VENDOR_QUOTE_OBSERVATIONS","source":provider,
            "exchange_verified":False,"buy_enabled":False,"new_baselines":0,
            "new_comparisons":0,"repeats_skipped":0,"stale_skipped":0,
            "invalid_skipped":0,"outcomes":[],"threshold_counts":{str(n):0 for n in THRESHOLDS}}
    rows=feed.get("results",[]) if isinstance(feed,dict) else []
    if isinstance(feed,dict) and feed.get("status")=="MISSING_API_KEY":
        output["status"]="MISSING_API_KEY"
        output["tracked_symbols"]=len(tracked)
        return state,output
    for row in rows:
        if not isinstance(row,dict):continue
        sym=row.get("symbol")
        if not isinstance(sym,str) or not sym or len(sym)>12:continue
        if row.get("status") not in ("RECENT_VENDOR_TIMESTAMP_UNVERIFIED","STALE_TIMESTAMP"):
            output["invalid_skipped"]+=1
            continue
        price=row.get("observed_price")
        timestamp=row.get("source_ts_utc")
        try:
            if isinstance(price,bool) or not isinstance(price,(float,int)) or not math.isfinite(price) or price<=0:raise ValueError()
            dt=datetime.fromisoformat(timestamp.replace("Z","+00:00"))
            if dt.tzinfo is None:raise ValueError()
            dt=dt.astimezone(timezone.utc)
        except (ValueError,TypeError,AttributeError,OverflowError):
            output["invalid_skipped"]+=1
            continue
        ts=dt.isoformat()
        existing=tracked.get(sym)
        if not isinstance(existing,dict):
            # Old/stale initial prices cannot serve as new entry baselines.
            if row["status"]!="RECENT_VENDOR_TIMESTAMP_UNVERIFIED":
                output["stale_skipped"]+=1
                continue
            tracked[sym]={"first_quote_utc":ts,"first_price":price,
                          "last_quote_utc":ts,"last_price":price,
                          "peak_price":price,"peak_return_pct":0.0,"comparisons":0}
            output["new_baselines"]+=1
            continue
        if ts<=str(existing.get("last_quote_utc","")):
            output["repeats_skipped"]+=1
            continue
        # A fresh timestamp, even for an older retrieved quote, constitutes a
        # later historical vendor observation; never claim realtime availability.
        first=existing["first_price"]
        if not isinstance(first,(float,int)) or first<=0:
            output["invalid_skipped"]+=1
            continue
        ret=round((price/first-1)*100,3)
        existing["last_quote_utc"]=ts
        existing["last_price"]=price
        existing["peak_price"]=max(existing.get("peak_price",first),price)
        existing["peak_return_pct"]=round((existing["peak_price"]/first-1)*100,3)
        existing["comparisons"]=existing.get("comparisons",0)+1
        output["new_comparisons"]+=1
        output["outcomes"].append({"symbol":sym,"first_quote_utc":existing["first_quote_utc"],
                                   "first_price":first,"later_quote_utc":ts,"later_price":price,
                                   "return_pct":ret,"peak_return_pct":existing["peak_return_pct"],
                                   "exchange_verified":False,"buy_enabled":False})
    output["tracked_symbols"]=len(tracked)
    output["threshold_counts"]={str(n):sum(item.get("peak_return_pct",0)>=n for item in tracked.values()) for n in THRESHOLDS}
    return state,output

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",default="vendor-quote-state.json")
    p.add_argument("--feed",default="cross-source-timing.json")
    p.add_argument("--out",default="vendor-quote-followup.json")
    a=p.parse_args()
    state_path=Path(a.state)
    try:state=json.loads(state_path.read_text()) if state_path.exists() else {}
    except (OSError,ValueError):state={}
    try:feed=json.loads(Path(a.feed).read_text())
    except (OSError,ValueError):feed={}
    state,report=reconcile(state,feed)
    state_path.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n")
    Path(a.out).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({key:report[key] for key in ("new_baselines","new_comparisons","repeats_skipped","stale_skipped","tracked_symbols","threshold_counts")}))
if __name__=="__main__":main()
