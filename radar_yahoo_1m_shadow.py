"""No-key Yahoo 1m completed-bar SHADOW observations; NEVER BUY.
Provider timestamp is not exchange-certified. Does not backfill first_seen.
"""
import argparse
import json
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo
from pathlib import Path

MAX_CHECKS=20
MAX_AGE=180
ET=ZoneInfo("America/New_York")

def inspect(symbol,payload,now):
    result={"symbol":symbol,"source":"Yahoo chart 1m (unofficial)","status":"BAD_SCHEMA",
            "validated_signal":False,"buy_enabled":False}
    try:
        chart=payload["chart"]["result"][0]
        meta=chart["meta"]
        stamps=chart["timestamp"]
        quotes=chart["indicators"]["quote"][0]
        closes=quotes["close"]
        volumes=quotes["volume"]
        ref=float(meta["chartPreviousClose"])
        if not 0<ref<1e9: return result
        # Only completed regular-session bars of the CURRENT NY calendar date.
        # Reject the forming minute and timestamps outside NYSE regular session.
        candidates=[]
        for stamp,close,vol in zip(stamps,closes,volumes):
            if close is None or vol is None:continue
            if isinstance(close,bool) or isinstance(vol,bool):continue
            ts=datetime.fromtimestamp(int(stamp),timezone.utc)
            local=ts.astimezone(ET)
            if local.date()!=now.astimezone(ET).date():continue
            if not (time(9,30)<=local.time()<time(16,0)):continue
            if ts+timedelta(minutes=1)>now:continue
            if not (0<float(close)<1e9 and 0<=int(vol)<1e15):continue
            candidates.append((ts,float(close),int(vol)))
        if not candidates:
            result["status"]="NO_COMPLETED_CURRENT_SESSION_BAR"
            return result
        ts,price,vol=max(candidates,key=lambda x:x[0])
        age=(now-ts-timedelta(minutes=1)).total_seconds()
        pct=100*(price/ref-1)
        result.update(source_timestamp_utc=ts.isoformat(),observed_at_utc=now.isoformat(),
                      completed_bar_end_utc=(ts+timedelta(minutes=1)).isoformat(),
                      bar_volume=vol,price=price,reference_close=ref,
                      reference_quality="VENDOR_CHART_PREVIOUS_CLOSE_UNVERIFIED",
                      percent_vs_reference=round(pct,4),age_seconds=round(age,1),
                      source_timestamp_certified=False)
        if age<0:result["status"]="FUTURE_BAR"
        elif age>MAX_AGE:result["status"]="STALE_BAR"
        elif not 3<=pct<=10:result["status"]="OUTSIDE_BAND"
        else:result["status"]="RECENT_COMPLETED_BAR_VENDOR_UNVERIFIED"
    except (KeyError,ValueError,TypeError,IndexError,OverflowError,AttributeError):
        pass
    return result

def fetch(symbol):
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol,safe="")+"?range=2d&interval=1m&includePrePost=false"
    request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urllib.request.urlopen(request,timeout=8) as r:
        data=r.read(500001)
    if len(data)>500000:raise ValueError("oversized")
    return json.loads(data)

def run(discovery,now=None,reader=fetch):
    now=now or datetime.now(timezone.utc)
    out={"checked_at_utc":now.isoformat(),"mode":"SHADOW","source":"Yahoo 1m",
         "orders_enabled":False,"validated_signals":0,"records":[]}
    symbols=[]
    for x in discovery.get("candidates",[]):
        sym=x.get("symbol","") if isinstance(x,dict) else ""
        if re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,9}",sym) and sym not in symbols: symbols.append(sym)
    for sym in symbols[:MAX_CHECKS]:
        try:out["records"].append(inspect(sym,reader(sym),now))
        except Exception as e:out["records"].append({"symbol":sym,"status":"SOURCE_ERROR","error_type":type(e).__name__,"validated_signal":False})
    return out

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--discovery",default="radar-discovery.json")
    parser.add_argument("--out",default="yahoo-1m-shadow.json")
    args=parser.parse_args()
    try:disc=json.loads(Path(args.discovery).read_text())
    except (ValueError,OSError):disc={}
    data=run(disc)
    Path(args.out).write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps({"checked":len(data["records"]),"status_counts":{s:sum(x["status"]==s for x in data["records"]) for s in {r["status"] for r in data["records"]}},"validated":0}))
if __name__=="__main__":main()
