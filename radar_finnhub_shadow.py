"""Optional timestamped Finnhub quote checks. READ-ONLY SHADOW, never BUY.
Requires FINNHUB_API_KEY supplied as GitHub Actions secret. A /quote
does NOT include volume or independently prove exchange timestamps.
"""
import argparse
import json
import math
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_CHECKS=20
MAX_AGE_SECONDS=180
def validate(symbol, data, now):
    out={"symbol":symbol,"provider":"Finnhub /quote","quality":"REJECTED",
         "signal_validated":False,"buy_enabled":False}
    try:
        price,ref,ts=data["c"],data["pc"],data["t"]
        if any(isinstance(v,bool) for v in (price,ref,ts)):raise ValueError()
        price,ref,ts=float(price),float(ref),int(ts)
        if not all(math.isfinite(v) and v>0 for v in (price,ref)) or ts<=0:raise ValueError()
        age=(now-datetime.fromtimestamp(ts,timezone.utc)).total_seconds()
        change=100*(price/ref-1)
        out.update(price=price,reference_close=ref,source_timestamp_utc=datetime.fromtimestamp(ts,timezone.utc).isoformat(),
                   observed_at_utc=now.isoformat(),age_seconds=round(age,1),
                   percent_vs_provider_previous_close=round(change,4),
                   volume=None,volume_quality="UNAVAILABLE_FROM_QUOTE_ENDPOINT")
        if age<0:out["quality"]="FUTURE_TIMESTAMP"
        elif age>MAX_AGE_SECONDS:out["quality"]="STALE"
        elif not 3<=change<=10:out["quality"]="OUTSIDE_ENTRY_BAND"
        else:out["quality"]="RECENT_VENDOR_TIMESTAMP_VOLUME_MISSING"
    except (ValueError,TypeError,KeyError,OverflowError):
        out["quality"]="INVALID_SCHEMA"
    return out

def fetch(symbol,key):
    url="https://finnhub.io/api/v1/quote?"+urllib.parse.urlencode({"symbol":symbol})
    req=urllib.request.Request(url,headers={"X-Finnhub-Token":key,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=7) as response:
        raw=response.read(250_001)
    if len(raw)>250_000:raise ValueError("oversized response")
    return json.loads(raw)

def run(discovery,key,now=None,reader=fetch):
    now=now or datetime.now(timezone.utc)
    out={"checked_at_utc":now.isoformat(),"mode":"SHADOW","buy_enabled":False,
         "provider":"Finnhub","verified_live_signals":0,"quote_source_exchange_verified":False,
         "status":"NO_KEY" if not key else "COMPLETED","records":[]}
    if not key:return out
    symbols=[]
    for entry in discovery.get("candidates",[]):
        sym=entry.get("symbol","") if isinstance(entry,dict) else ""
        if re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,9}",sym) and sym not in symbols:
            symbols.append(sym)
    for sym in symbols[:MAX_CHECKS]:
        try:out["records"].append(validate(sym,reader(sym,key),now))
        except Exception as exc:
            out["records"].append({"symbol":sym,"quality":"SOURCE_ERROR","error_type":type(exc).__name__,
                                  "signal_validated":False,"buy_enabled":False})
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--discovery",default="radar-discovery.json")
    p.add_argument("--out",default="timestamped-quote-diagnostics.json")
    args=p.parse_args()
    try:discovery=json.loads(Path(args.discovery).read_text())
    except (OSError,ValueError):discovery={}
    result=run(discovery,os.environ.get("FINNHUB_API_KEY",""))
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"checked":len(result["records"]),
        "recent_in_band":sum(r["quality"]=="RECENT_VENDOR_TIMESTAMP_VOLUME_MISSING" for r in result["records"]),
        "validated":0}))
if __name__=="__main__":main()
