"""SAG-30 v0.4.3 PATH-OBSERVABILITY DIAGNOSTIC SHADOW.
Research-only. No signal semantic change from v0.4.2. Never authorizes BUY.
"""
import argparse, json, os
from datetime import datetime, timedelta, timezone, time as dtime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import load_universe, daily, sessions, bounds, median
from research.fast_path_v042_replay import request_json_resilient

ET=ZoneInfo("America/New_York")

def replay_one(e,headers,feed,max_gap=5.0):
    start,end=bounds(e["date"])
    d=request_json_resilient(f'/v2/stocks/{e["symbol"]}/bars',
      {"timeframe":"1Min","start":start,"end":end,"feed":feed,"limit":10000,"adjustment":"all"},headers)
    bars=sorted(d.get("bars") or [],key=lambda x:x["t"])
    prev=e["prev_close"]
    prior_pct=prior_ts=None
    positive_streak=positive_total=0
    max_positive_streak=0
    eligible_usable=0
    prearm=trigger=first30=first50=None
    intervals=usable=consecutive=gaps=0
    max_accel_under10=None
    max_interval_gain_under10=None
    for b in bars:
        close=float(b.get("c") or 0); high=float(b.get("h") or 0); vol=float(b.get("v") or 0)
        if close<=0 or high<=0:
            continue
        ts=datetime.fromisoformat(b["t"].replace("Z","+00:00"))
        pct=(close/prev-1)*100; hp=(high/prev-1)*100
        if first30 is None and hp>=30:
            first30=ts
        if first50 is None and hp>=50:
            first50=ts
        eligible=first30 is None
        accel=None; gain=None
        if prior_ts is not None:
            dt=(ts-prior_ts).total_seconds()/60
            if dt>0:
                intervals+=1
                consecutive+=int(0.5<=dt<=1.5)
                if dt<=max_gap:
                    usable+=1
                    gain=pct-prior_pct
                    accel=gain/dt
                else:
                    gaps+=1
                    positive_streak=0
        interval_eligible=eligible and accel is not None and 0<pct<10
        if interval_eligible:
            eligible_usable+=1
            max_accel_under10=accel if max_accel_under10 is None else max(max_accel_under10,accel)
            max_interval_gain_under10=gain if max_interval_gain_under10 is None else max(max_interval_gain_under10,gain)
        positive=interval_eligible and accel>0 and vol>0
        if positive:
            positive_total+=1
            positive_streak+=1
            max_positive_streak=max(max_positive_streak,positive_streak)
        else:
            positive_streak=0
        if eligible and prearm is None and 0<pct<10 and positive_streak>=2:
            prearm=ts
        if eligible and trigger is None and prearm is not None and ts>prearm and 2<=pct<10 and accel is not None and accel>0:
            trigger=ts
        prior_pct,prior_ts=pct,ts
    path_observable=eligible_usable>=2
    if prearm is not None:
        miss_class="DETECTED"
    elif not path_observable:
        miss_class="PATH_UNOBSERVABLE"
    elif positive_total>=2:
        miss_class="PERSISTENCE_MISS"
    else:
        miss_class="FLOW_MISS"
    lead=lambda a,b: None if a is None or b is None else (b-a).total_seconds()/60
    preopen30=bool(first30 and first30.astimezone(ET).time()<dtime(9,30))
    return {**e,"bars":len(bars),"intervals":intervals,
      "consecutive_intervals":consecutive,
      "consecutive_rate":consecutive/intervals if intervals else None,
      "event_time_usable_intervals":usable,
      "event_time_usable_rate":usable/intervals if intervals else None,
      "data_gaps_gt5m":gaps,
      "eligible_sub10_usable_intervals":eligible_usable,
      "positive_eligible_intervals_total":positive_total,
      "max_positive_streak":max_positive_streak,
      "max_accel_under10":max_accel_under10,
      "max_interval_gain_under10":max_interval_gain_under10,
      "path_observable":path_observable,
      "miss_class":miss_class,
      "first30_before_0930_et":preopen30,
      "prearm_ts":prearm.isoformat() if prearm else None,
      "trigger_ts":trigger.isoformat() if trigger else None,
      "first30_ts":first30.isoformat() if first30 else None,
      "first50_ts":first50.isoformat() if first50 else None,
      "prearm_under10":prearm is not None,
      "trigger_under10":trigger is not None,
      "prearm_lead30_min":lead(prearm,first30),
      "trigger_lead30_min":lead(trigger,first30)}

def summarize(win,non):
    w,n=len(win),len(non)
    wp=sum(x["prearm_under10"] for x in win); wt=sum(x["trigger_under10"] for x in win)
    np=sum(x["prearm_under10"] for x in non); nt=sum(x["trigger_under10"] for x in non)
    po=[x for x in win if x["path_observable"]]
    classes={k:sum(x["miss_class"]==k for x in win) for k in ["DETECTED","PATH_UNOBSERVABLE","PERSISTENCE_MISS","FLOW_MISS"]}
    return {"winner_count":w,"nonwinner_count":n,
      "winner_prearm_recall":wp/w if w else None,
      "winner_trigger_recall":wt/w if w else None,
      "prearm_precision_to_30":wp/(wp+np) if wp+np else None,
      "trigger_precision_to_30":wt/(wt+nt) if wt+nt else None,
      "nonwinner_prearm_false_positive_rate":np/n if n else None,
      "nonwinner_trigger_false_positive_rate":nt/n if n else None,
      "median_prearm_lead30_min":median([x["prearm_lead30_min"] for x in win]),
      "median_trigger_lead30_min":median([x["trigger_lead30_min"] for x in win]),
      "winner_event_time_usable_rate":median([x["event_time_usable_rate"] for x in win]),
      "nonwinner_event_time_usable_rate":median([x["event_time_usable_rate"] for x in non]),
      "path_observable_winners":len(po),
      "path_observable_prearm_recall":sum(x["prearm_under10"] for x in po)/len(po) if po else None,
      "winner_miss_taxonomy":classes,
      "winner_first30_before_0930_et":sum(x["first30_before_0930_et"] for x in win),
      "preopen30_detected":sum(x["first30_before_0930_et"] and x["prearm_under10"] for x in win)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--universe",default="config/universe.csv"); p.add_argument("--out",default="research/fast_path_v043_diagnostic.json")
    p.add_argument("--winners",type=int,default=300); p.add_argument("--nonwinners",type=int,default=300)
    p.add_argument("--lookback-days",type=int,default=240); p.add_argument("--feed",default="iex"); p.add_argument("--workers",type=int,default=2)
    a=p.parse_args()
    h={"APCA-API-KEY-ID":os.environ["ALPACA_API_KEY"],"APCA-API-SECRET-KEY":os.environ["ALPACA_SECRET_KEY"]}
    end=datetime.now(timezone.utc); start=end-timedelta(days=a.lookback_days)
    dm=daily(load_universe(a.universe),start.isoformat(),end.isoformat(),h,a.feed)
    winners,non=sessions(dm); winners=winners[:a.winners]; non=non[:a.nonwinners]
    def run(rows):
        out=[]
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            fs=[pool.submit(replay_one,e,h,a.feed) for e in rows]
            for f in as_completed(fs):
                out.append(f.result())
        return out
    wr,nr=run(winners),run(non)
    s=summarize(wr,nr)
    gates={"recall_ge_35pct":s["winner_prearm_recall"]>=.35,
      "prearm_precision_ge_8pct":s["prearm_precision_to_30"]>=.08,
      "trigger_precision_ge_12pct":s["trigger_precision_to_30"]>=.12,
      "median_prearm_lead_ge_3m":(s["median_prearm_lead30_min"] or -1)>=3,
      "historical_only_no_promotion":True}
    payload={"status":"DIAGNOSTIC_ONLY","version":"v0.4.3-PATH-OBSERVABILITY-SHADOW",
      "authoritative":False,"buy":False,"generated_at":datetime.now(timezone.utc).isoformat(),
      "signal_semantics":"unchanged from v0.4.2",
      "hypothesis":"separate path-unobservable, persistence-miss and flow-miss winner classes before changing FLOW",
      "summary":s,"gates":gates,
      "limitations":["retrospective/in-sample","current-universe survivorship bias","IEX partial-market coverage","diagnostic version does not authorize threshold tuning","bar replay cannot prove fills/spreads"],
      "winners":wr,"nonwinners":nr}
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10))
    print(json.dumps({"summary":s,"gates":gates},sort_keys=True))

if __name__=="__main__":
    main()
