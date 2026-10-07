"""SAG-30 v0.4.2 EVENT-TIME FLOW SHADOW calibration.
Research-only. v0.3.3 FROZEN is untouched. Never authorizes BUY.

Single pre-registered hypothesis: sparse IEX observations should not be treated as
negative FLOW merely because adjacent timestamps are not exactly one minute apart.
Use observed event-time velocity for gaps <=5 minutes; gaps >5 minutes reset FLOW.
Signals at/after first +30% are ineligible (prevents post-explosion credit).
"""
import argparse, json
from research.fast_path_v041_replay import load_universe,daily,sessions,bounds,request_json,median
import os,time,random\nfrom urllib.error import HTTPError
from datetime import datetime,timedelta,timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed

def request_json_resilient(path, params, headers, attempts=8):
    """Infrastructure-only: retry HTTP 429 with bounded exponential backoff."""
    for attempt in range(attempts):
        try:
            return request_json(path, params, headers)
        except HTTPError as exc:
            if exc.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(min(60.0, 2.0 ** attempt) + random.uniform(0.0, 0.75))

def replay_one(e,headers,feed,max_gap=5.0):
    start,end=bounds(e["date"])
    d=request_json_resilient(f'/v2/stocks/{e["symbol"]}/bars',{"timeframe":"1Min","start":start,"end":end,"feed":feed,"limit":10000,"adjustment":"all"},headers)
    bars=sorted(d.get("bars") or [],key=lambda x:x["t"]); prev=e["prev_close"]
    prior_pct=prior_ts=None; positive_count=0; prearm=trigger=first30=first50=None
    intervals=usable=consecutive=gaps=0
    for b in bars:
        close=float(b.get("c") or 0); high=float(b.get("h") or 0); vol=float(b.get("v") or 0)
        if close<=0 or high<=0: continue
        ts=datetime.fromisoformat(b["t"].replace("Z","+00:00")); pct=(close/prev-1)*100; hp=(high/prev-1)*100
        if first30 is None and hp>=30:first30=ts
        if first50 is None and hp>=50:first50=ts
        # Once +30% has occurred, later observations cannot earn PRE-ARM/TRIGGER credit.
        eligible=first30 is None
        accel=None
        if prior_ts is not None:
            dt=(ts-prior_ts).total_seconds()/60
            if dt>0:
                intervals+=1; consecutive+=int(0.5<=dt<=1.5)
                if dt<=max_gap: usable+=1; accel=(pct-prior_pct)/dt
                else: gaps+=1; positive_count=0
        positive=eligible and accel is not None and 0<pct<10 and accel>0 and vol>0
        positive_count=positive_count+1 if positive else 0
        if eligible and prearm is None and 0<pct<10 and positive_count>=2: prearm=ts
        if eligible and trigger is None and prearm is not None and ts>prearm and 2<=pct<10 and accel is not None and accel>0: trigger=ts
        prior_pct,prior_ts=pct,ts
    lead=lambda a,b: None if a is None or b is None else (b-a).total_seconds()/60
    return {**e,"bars":len(bars),"intervals":intervals,"consecutive_intervals":consecutive,
      "consecutive_rate":consecutive/intervals if intervals else None,
      "event_time_usable_intervals":usable,"event_time_usable_rate":usable/intervals if intervals else None,
      "data_gaps_gt5m":gaps,"prearm_ts":prearm.isoformat() if prearm else None,
      "trigger_ts":trigger.isoformat() if trigger else None,"first30_ts":first30.isoformat() if first30 else None,
      "first50_ts":first50.isoformat() if first50 else None,"prearm_under10":prearm is not None,
      "trigger_under10":trigger is not None,"prearm_lead30_min":lead(prearm,first30),"trigger_lead30_min":lead(trigger,first30)}

def summarize(win,non):
    w,n=len(win),len(non); wp=sum(x["prearm_under10"] for x in win); wt=sum(x["trigger_under10"] for x in win)
    np=sum(x["prearm_under10"] for x in non); nt=sum(x["trigger_under10"] for x in non)
    return {"winner_count":w,"nonwinner_count":n,"winner_prearm_recall":wp/w if w else None,
      "winner_trigger_recall":wt/w if w else None,"prearm_precision_to_30":wp/(wp+np) if wp+np else None,
      "trigger_precision_to_30":wt/(wt+nt) if wt+nt else None,"nonwinner_prearm_false_positive_rate":np/n if n else None,
      "nonwinner_trigger_false_positive_rate":nt/n if n else None,
      "median_prearm_lead30_min":median([x["prearm_lead30_min"] for x in win]),
      "median_trigger_lead30_min":median([x["trigger_lead30_min"] for x in win]),
      "winner_consecutive_1m_rate":median([x["consecutive_rate"] for x in win]),
      "nonwinner_consecutive_1m_rate":median([x["consecutive_rate"] for x in non]),
      "winner_event_time_usable_rate":median([x["event_time_usable_rate"] for x in win]),
      "nonwinner_event_time_usable_rate":median([x["event_time_usable_rate"] for x in non])}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--universe",default="config/universe.csv");p.add_argument("--out",default="research/fast_path_v042_replay.json")
    p.add_argument("--winners",type=int,default=300);p.add_argument("--nonwinners",type=int,default=300);p.add_argument("--lookback-days",type=int,default=240)
    p.add_argument("--feed",default="iex");p.add_argument("--workers",type=int,default=2);a=p.parse_args()
    h={"APCA-API-KEY-ID":os.environ["ALPACA_API_KEY"],"APCA-API-SECRET-KEY":os.environ["ALPACA_SECRET_KEY"]}
    end=datetime.now(timezone.utc);start=end-timedelta(days=a.lookback_days); dm=daily(load_universe(a.universe),start.isoformat(),end.isoformat(),h,a.feed)
    winners,non=sessions(dm); winners=winners[:a.winners];non=non[:a.nonwinners]
    def run(rows):
        out=[]
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            fs=[pool.submit(replay_one,e,h,a.feed) for e in rows]
            for f in as_completed(fs):out.append(f.result())
        return out
    wr,nr=run(winners),run(non); s=summarize(wr,nr)
    gates={"recall_ge_35pct":s["winner_prearm_recall"]>=.35,"prearm_precision_ge_8pct":s["prearm_precision_to_30"]>=.08,
      "trigger_precision_ge_12pct":s["trigger_precision_to_30"]>=.12,"median_prearm_lead_ge_3m":(s["median_prearm_lead30_min"] or -1)>=3,
      "historical_only_no_promotion":True}
    payload={"status":"CALIBRATION_ONLY","version":"v0.4.2-SHADOW","authoritative":False,"buy":False,"generated_at":datetime.now(timezone.utc).isoformat(),
      "hypothesis":"event-time FLOW across observed gaps <=5m recovers sparse-IEX recall without uncontrolled false positives","max_event_gap_min":5,
      "summary":s,"gates":gates,"limitations":["retrospective/in-sample","current-universe survivorship bias","IEX partial-market coverage","bar replay cannot prove fills/spreads","FLOW-only"],"winners":wr,"nonwinners":nr}
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n");print(json.dumps({"summary":s,"gates":gates},sort_keys=True))
if __name__=="__main__":main()
