"""Optional Twelve Data 1-minute bars for read-only SHADOW stock outcome tracking.

Requires TWELVE_DATA_API_KEY in GitHub Actions secrets. No trading endpoints.
Returns actual bar-start timestamps, never substitutes the retrieval timestamp.
"""
import argparse
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_SYMBOLS=6  # free Basic: 8 API credits/min, <=800/day
MAX_BYTES=300000
def parse(symbol,payload,now):
    out={"symbol":symbol,"source":"Twelve Data time_series 1min",
         "status":"BAD_SCHEMA","eligible_for_first_watch":False,
         "source_timestamp_verified_by_exchange":False}
    try:
        if not isinstance(payload,dict) or payload.get("status")=="error":
            out["status"]="PROVIDER_ERROR"
            return out
        meta=payload["meta"]
        if meta.get("interval")!="1min" or str(meta.get("symbol","")).upper()!=symbol:
            return out
        values=payload["values"]
        if not isinstance(values,list) or not values:return out
        # API timezone=UTC; datetime is bar START (not retrieval or last trade).
        bar=values[0]
        stamp=datetime.strptime(bar["datetime"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        close=float(bar["close"])
        if not math.isfinite(close) or not 0<close<1e9:return out
        age=(now-stamp).total_seconds()
        out.update(observed_price=close,source_ts_utc=stamp.isoformat(),
                   retrieval_utc=now.isoformat(),age_seconds=round(age,1),
                   quote_kind="1MIN_BAR_CLOSE",bar_timestamp_semantics="BAR_START_UTC")
        # 1-min bar is complete only after end; avoid incomplete or future bars.
        if age<60:out["status"]="INCOMPLETE_OR_FUTURE_BAR"
        elif age>360:out["status"]="STALE_TIMESTAMP"
        else:out["status"]="RECENT_VENDOR_TIMESTAMP_UNVERIFIED"
    except (KeyError,IndexError,ValueError,TypeError,OverflowError,AttributeError):
        pass
    return out

def fetch(symbol,key,opener=None):
    opener=opener or urllib.request.urlopen
    if not re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,9}",symbol):raise ValueError("invalid symbol")
    query=urllib.parse.urlencode({"symbol":symbol,"interval":"1min",
        "timezone":"UTC","outputsize":2,"apikey":key})
    # Key never logged, written to artifacts or committed.
    req=urllib.request.Request("https://api.twelvedata.com/time_series?"+query,
                               headers={"Accept":"application/json"})
    with opener(req,timeout=8) as response:
        raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError("oversized response")
    return json.loads(raw)

def run(discovery,prior=None,now=None,key=None,request=None):
    now=now or datetime.now(timezone.utc)
    key=key if key is not None else os.environ.get("TWELVE_DATA_API_KEY","")
    result={"provider":"Twelve Data","mode":"READ_ONLY_SHADOW",
            "status":"MISSING_API_KEY" if not key else "CHECKED",
            "buy_enabled":False,"verified_live_signals":0,
            "requested":0,"results":[]}
    if not key:return result
    prior=prior if isinstance(prior,dict) else {}
    new=discovery.get("candidates",[]) if isinstance(discovery,dict) else []
    symbols=list(prior.get("symbols",{}))+[c.get("symbol") for c in new if isinstance(c,dict)]
    seen=set()
    for sym in symbols:
        if not isinstance(sym,str) or not re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,9}",sym) or sym in seen:continue
        if len(seen)>=MAX_SYMBOLS:break
        seen.add(sym)
        result["requested"]+=1
        try:record=parse(sym,(request or fetch)(sym,key),now)
        except (ValueError,TypeError,KeyError,urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError):
            record={"symbol":sym,"status":"SOURCE_UNAVAILABLE","eligible_for_first_watch":False}
        result["results"].append(record)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--discovery",default="radar-discovery.json")
    p.add_argument("--state",default="twelve-data-quote-state.json")
    p.add_argument("--out",default="twelve-data-quotes.json")
    a=p.parse_args()
    try:discovery=json.loads(Path(a.discovery).read_text())
    except (OSError,ValueError):discovery={}
    try:prior=json.loads(Path(a.state).read_text())
    except (OSError,ValueError):prior={}
    report=run(discovery,prior)
    Path(a.out).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"provider":report["provider"],"status":report["status"],
                      "requested":report["requested"],"statuses":[x["status"] for x in report["results"]]}))
if __name__=="__main__":main()
