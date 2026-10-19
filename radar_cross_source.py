"""Read-only cross-source timing diagnostics for a tiny candidate sample.

Yahoo chart is an unofficial endpoint; it does NOT prove exchange coverage,
realtime tradability, or authoritative reference close. Never emits BUY.
"""
import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MAX_CHECKS=40
MAX_BYTES=300000
def inspect_chart(symbol, payload, now):
    out={"symbol":symbol,"source":"Yahoo public chart (unofficial)",
         "status":"BAD_SCHEMA","eligible_for_first_watch":False}
    try:
        result=payload["chart"]["result"][0]
        meta=result["meta"]
        price=meta["regularMarketPrice"]
        close=meta["chartPreviousClose"]
        epoch=meta["regularMarketTime"]
        if isinstance(price,bool) or isinstance(close,bool) or isinstance(epoch,bool):
            return out
        price=float(price);close=float(close);epoch=int(epoch)
        if not (0<price<1e9 and 0<close<1e9 and epoch>0):return out
        source_dt=datetime.fromtimestamp(epoch,timezone.utc)
        age=(now-source_dt).total_seconds()
        eastern=source_dt.astimezone(ZoneInfo("America/New_York"))
        out.update(source_ts_utc=source_dt.isoformat(),retrieval_utc=now.isoformat(),
            age_seconds=round(age,1),reported_pct_vs_yahoo_reference=round((price/close-1)*100,3),
            source_regular_session_date=eastern.date().isoformat())
        if age<0:out["status"]="FUTURE_TIMESTAMP"
        elif age>120:out["status"]="STALE_TIMESTAMP"
        else:out["status"]="RECENT_VENDOR_TIMESTAMP_UNVERIFIED"
        out["source_timestamp_verified_by_exchange"]=False
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,AttributeError):
        pass
    return out

def query(symbol, opener=None):
    opener=opener or urllib.request.urlopen
    safe=urllib.parse.quote(symbol,safe="")
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{safe}?range=1d&interval=1m"
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0"})
    with opener(req,timeout=8) as response:
        data=response.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:raise ValueError("oversized chart")
    return json.loads(data)

def run(discovery, now=None, fetch=None):
    now=now or datetime.now(timezone.utc)
    fetch=fetch or query
    entries=discovery.get("candidates",[]) if isinstance(discovery,dict) else []
    res={"checked_at_utc":now.isoformat(),"mode":"SHADOW_TIMING_DIAGNOSTIC",
         "verified_live_signals":0,"orders_enabled":False,"requested":0,
         "results":[],"source_realtime_verified":False}
    for c in entries[:MAX_CHECKS]:
        symbol=str(c.get("symbol","")) if isinstance(c,dict) else ""
        if not re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,9}",symbol):continue
        res["requested"]+=1
        try:record=inspect_chart(symbol,fetch(symbol),now)
        except (ValueError,TypeError,KeyError,urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError):
            record={"symbol":symbol,"status":"SOURCE_UNAVAILABLE","eligible_for_first_watch":False}
        res["results"].append(record)
    return res

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--discovery",default="radar-discovery.json")
    p.add_argument("--out",default="cross-source-timing.json")
    a=p.parse_args()
    try:discovery=json.loads(Path(a.discovery).read_text())
    except (OSError,ValueError): discovery={}
    report=run(discovery)
    Path(a.out).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"cross_source_checked":report["requested"],"statuses":[x["status"] for x in report["results"]],"verified_live_signals":0}))

if __name__=="__main__":main()
