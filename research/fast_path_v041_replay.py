"""v0.4.1 retrospective 1-minute calibration replay.

Builds a balanced cohort of:
- winners: session high >= +30%
- non-winners: session high >= +5% and < +30%

Replays 1-minute bars with no look-ahead and evaluates FLOW-only PREARM/TRIGGER logic.
EVENT statistics remain separate because historical headline timing is evaluated by the
existing winner300 stress test and must not be conflated with FLOW calibration.

Research-only; never authorizes BUY.
"""
import argparse, csv, json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
API="https://data.alpaca.markets"

def request_json(path,params,headers,retries=6):
    url=API+path+"?"+urlencode(params)
    for attempt in range(retries):
        try:
            with urlopen(Request(url,headers=headers),timeout=45) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==retries-1: raise
            time.sleep(min(2**attempt,20))
    raise RuntimeError("request retries exhausted")

def load_universe(path):
    with open(path,newline="") as f:
        return sorted({r["symbol"].strip().upper() for r in csv.DictReader(f) if r.get("symbol")})

def daily(symbols,start,end,headers,feed):
    out={}
    for off in range(0,len(symbols),100):
        token=None; batch=symbols[off:off+100]
        while True:
            p={"symbols":",".join(batch),"timeframe":"1Day","start":start,"end":end,"feed":feed,"limit":10000,"adjustment":"all"}
            if token:p["page_token"]=token
            d=request_json("/v2/stocks/bars",p,headers)
            for s,b in (d.get("bars") or {}).items():out.setdefault(s,[]).extend(b or [])
            token=d.get("next_page_token")
            if not token:break
    return out

def sessions(daily_map):
    winners=[]; non=[]
    for symbol,bars in daily_map.items():
        prev=None
        for b in sorted(bars,key=lambda x:x["t"]):
            if prev and prev>0:
                hi=float(b.get("h") or 0)
                if hi>0:
                    pct=(hi/prev-1)*100
                    row={"symbol":symbol,"date":b["t"][:10],"prev_close":prev,"daily_high_pct":pct}
                    if pct>=30:winners.append(row)
                    elif pct>=5:non.append(row)
            c=float(b.get("c") or 0)
            if c>0:prev=c
    key=lambda x:(x["date"],x["daily_high_pct"],x["symbol"])
    return sorted(winners,key=key,reverse=True),sorted(non,key=key,reverse=True)

def bounds(date):
    d=datetime.fromisoformat(date).replace(tzinfo=ET)
    return d.replace(hour=4,minute=0).isoformat(),d.replace(hour=20,minute=0).isoformat()

def replay_one(e,headers,feed):
    start,end=bounds(e["date"])
    d=request_json(f'/v2/stocks/{e["symbol"]}/bars',{
      "timeframe":"1Min","start":start,"end":end,"feed":feed,"limit":10000,"adjustment":"all"
    },headers)
    bars=sorted(d.get("bars") or [],key=lambda x:x["t"])
    prev=e["prev_close"]
    prior_pct=None; prior_ts=None
    positive_count=0
    prearm=None; trigger=None; first30=None; first50=None
    valid_intervals=0; consecutive_intervals=0
    for b in bars:
        close=float(b.get("c") or 0); high=float(b.get("h") or 0); vol=float(b.get("v") or 0)
        if close<=0 or high<=0:continue
        ts=datetime.fromisoformat(b["t"].replace("Z","+00:00"))
        pct=(close/prev-1)*100
        high_pct=(high/prev-1)*100
        if first30 is None and high_pct>=30:first30=ts
        if first50 is None and high_pct>=50:first50=ts
        accel=0.0; consecutive=False
        if prior_ts is not None:
            dt=(ts-prior_ts).total_seconds()/60
            if dt>0:
                valid_intervals+=1
                consecutive=(0.5<=dt<=1.5)
                consecutive_intervals+=int(consecutive)
                accel=(pct-prior_pct)/dt
        positive=(consecutive and 0<pct<10 and accel>0 and vol>0)
        positive_count=positive_count+1 if positive else 0
        if prearm is None and 0<pct<10 and positive_count>=2:
            prearm=ts
        if trigger is None and prearm is not None and ts>prearm and 2<=pct<10 and accel>0:
            trigger=ts
        prior_pct,prior_ts=pct,ts
    def lead(a,b):
        if a is None or b is None:return None
        return (b-a).total_seconds()/60
    return {
      **e,"bars":len(bars),
      "intervals":valid_intervals,"consecutive_intervals":consecutive_intervals,
      "consecutive_rate":(consecutive_intervals/valid_intervals if valid_intervals else None),
      "prearm_ts":prearm.isoformat() if prearm else None,
      "trigger_ts":trigger.isoformat() if trigger else None,
      "first30_ts":first30.isoformat() if first30 else None,
      "first50_ts":first50.isoformat() if first50 else None,
      "prearm_under10":prearm is not None,
      "trigger_under10":trigger is not None,
      "prearm_lead30_min":lead(prearm,first30),
      "trigger_lead30_min":lead(trigger,first30),
    }

def median(v):
    v=sorted(x for x in v if x is not None)
    if not v:return None
    n=len(v);return v[n//2] if n%2 else (v[n//2-1]+v[n//2])/2

def summarize(win,non):
    w=len(win);n=len(non)
    wp=sum(e["prearm_under10"] for e in win);wt=sum(e["trigger_under10"] for e in win)
    np=sum(e["prearm_under10"] for e in non);nt=sum(e["trigger_under10"] for e in non)
    prearm_total=wp+np; trigger_total=wt+nt
    return {
      "winner_count":w,"nonwinner_count":n,
      "winner_prearm_recall":wp/w if w else None,
      "winner_trigger_recall":wt/w if w else None,
      "prearm_precision_to_30":wp/prearm_total if prearm_total else None,
      "trigger_precision_to_30":wt/trigger_total if trigger_total else None,
      "nonwinner_prearm_false_positive_rate":np/n if n else None,
      "nonwinner_trigger_false_positive_rate":nt/n if n else None,
      "median_prearm_lead30_min":median([e["prearm_lead30_min"] for e in win]),
      "median_trigger_lead30_min":median([e["trigger_lead30_min"] for e in win]),
      "winner_consecutive_1m_rate":median([e["consecutive_rate"] for e in win]),
      "nonwinner_consecutive_1m_rate":median([e["consecutive_rate"] for e in non]),
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--universe",default="config/universe.csv")
    p.add_argument("--out",default="research/fast_path_v041_replay.json")
    p.add_argument("--winners",type=int,default=300)
    p.add_argument("--nonwinners",type=int,default=300)
    p.add_argument("--lookback-days",type=int,default=240)
    p.add_argument("--feed",default="iex")
    p.add_argument("--workers",type=int,default=6)
    a=p.parse_args()
    h={"APCA-API-KEY-ID":os.environ["ALPACA_API_KEY"],"APCA-API-SECRET-KEY":os.environ["ALPACA_SECRET_KEY"]}
    end=datetime.now(timezone.utc); start=end-timedelta(days=a.lookback_days)
    dm=daily(load_universe(a.universe),start.isoformat(),end.isoformat(),h,a.feed)
    winners,non=sessions(dm)
    winners=winners[:a.winners]; non=non[:a.nonwinners]
    def run(rows):
        out=[]
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            fut=[pool.submit(replay_one,e,h,a.feed) for e in rows]
            for f in as_completed(fut):out.append(f.result())
        return out
    wr=run(winners); nr=run(non)
    payload={
      "status":"CALIBRATION_ONLY","authoritative":False,"buy":False,
      "generated_at":datetime.now(timezone.utc).isoformat(),"feed":a.feed,
      "summary":summarize(wr,nr),
      "limitations":[
        "in-sample retrospective calibration",
        "current-universe survivorship bias",
        "IEX partial-market coverage",
        "bar replay does not prove executable fills or historical ask spreads",
        "FLOW-only replay; EVENT timing must be reported separately"
      ],
      "winners":wr,"nonwinners":nr
    }
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload["summary"],sort_keys=True))

if __name__=="__main__":main()
