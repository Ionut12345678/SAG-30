"""Fetch actual historical five-minute US-session candles for RESEARCH only.

Fixed retrospective cohort includes suspected runners AND controls; it is not a
random sample and cannot estimate future predictive accuracy. Source Yahoo chart
is unofficial, vendor OHLCV timestamps are not exchange-certified.
"""
import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime,timezone,time as clock
from pathlib import Path
from zoneinfo import ZoneInfo
from radar_historical_replay import replay,summarize

# Frozen before evaluating this cohort; not a statistical performance sample.
COHORT=(
    "SAIQ","MYGN","VOGX","IRLA","LRMR","FISN","ARQQ","CHPT",
    "RUN","SGMT","CCCC","ATOS","ALOY","NFE","KXIN","OPTH",
    "OIO","FFR","ARMP","GMHS","BHST","LVLU","MODD","GRNT",
    "MTDR","ATNM","NOMA","HPK","ALXO","NOG","SM","KGEI",
    "SOUN","PLTR","NVDA","AMD","IONQ","RGTI","QBTS","MARA",
    "RIOT","SOFI","HIMS","UPST","RKLB","LUNR","ASTS","ACHR"
)
EAST=ZoneInfo("America/New_York")
def fetch(symbol,opener=None):
    opener=opener or urllib.request.urlopen
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol,safe="")+"?interval=5m&range=1mo&includePrePost=true"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with opener(req,timeout=9) as response:data=response.read(500001)
    if len(data)>500000:raise ValueError("oversized")
    return json.loads(data)

def extract(symbol,payload):
    try:
        data=payload["chart"]["result"][0]
        times=data["timestamp"]
        quotes=data["indicators"]["quote"][0]
        dates={}
        for i,epoch in enumerate(times):
            ts=datetime.fromtimestamp(int(epoch),timezone.utc)
            local=ts.astimezone(EAST)
            if not clock(9,30)<=local.time()<clock(16,0):continue
            values=[quotes[k][i] for k in ("open","high","low","close","volume")]
            if any(x is None for x in values):continue
            o,h,l,c,v=[float(x) for x in values]
            if not all(math.isfinite(x) for x in (o,h,l,c,v)) or l<=0 or v<0:continue
            bar={"ts":ts.isoformat(),"open":o,"high":h,"low":l,"close":c,"volume":v}
            dates.setdefault(local.date().isoformat(),[]).append(bar)
        outputs=[]
        ordered=sorted(dates)
        for j in range(1,len(ordered)):
            prev=dates[ordered[j-1]]
            current=dates[ordered[j]]
            # Exact previous trading day's last regular-hours close.
            if len(prev)<20 or len(current)<4:continue
            ref=prev[-1]["close"]
            out=replay(symbol,current,ref)
            out["session"]=ordered[j]
            out["previous_session"]=ordered[j-1]
            outputs.append(out)
        return outputs
    except (TypeError,ValueError,KeyError,IndexError,OverflowError,AttributeError):
        return [{"symbol":symbol,"status":"INVALID_FEED"}]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="historical-real-replay.json")
    args=p.parse_args()
    outcomes=[]
    errors=[]
    for symbol in COHORT:
        try:
            outcomes.extend(extract(symbol,fetch(symbol)))
        except Exception as exc:
            errors.append({"symbol":symbol,"error_type":type(exc).__name__})
        time.sleep(.15)
    summary=summarize(outcomes)
    summary.update(source="Yahoo unofficial 5m bars",cohort=list(COHORT),
        collection_errors=errors,source_verified_by_exchange=False,
        cohort_selected_retrospectively=True,
        calibration_allowed=False,
        realtime_fill_proven=False)
    Path(args.out).write_text(json.dumps({"summary":summary,"results":outcomes},indent=2)+"\n")
    print(json.dumps({k:summary[k] for k in ("cases","evaluated","winner_20_count","false_winner_under_20_count","collection_errors")}))
if __name__=="__main__":main()
