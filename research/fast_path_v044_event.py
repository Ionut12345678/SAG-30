"""SAG-30 v0.4.4 balanced EVENT coverage SHADOW.
Pre-registered research-only EVENT routing test. Never authorizes BUY.
"""
import argparse,json,os
from datetime import datetime,timedelta,timezone,time as dtime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import load_universe,daily,sessions,bounds,median
from research.fast_path_v042_replay import request_json_resilient

ET=ZoneInfo("America/New_York")
CATALYSTS={
 "ANTI_DILUTION_BUYBACK":("buyback","repurchase","at-the-market","atm","suspend"),
 "MNA":("merger","acquisition","acquire","strategic combination","business combination"),
 "CONTRACT":("contract","agreement","award","order","purchase order","customer"),
 "FDA_CLINICAL":("fda","clinical","trial","phase 1","phase 2","phase 3","topline"),
 "GOV_DEFENSE":("department of defense","dod","government","federal","army","navy","air force","grant"),
 "EARNINGS":("earnings","results","revenue","guidance"),
 "PATENT_TECH":("patent","technology","platform","artificial intelligence","blockchain"),
}

def path_one(e,headers,feed,max_gap=5.0):
    start,end=bounds(e["date"])
    d=request_json_resilient(f'/v2/stocks/{e["symbol"]}/bars',
      {"timeframe":"1Min","start":start,"end":end,"feed":feed,"limit":10000,"adjustment":"all"},headers)
    bars=sorted(d.get("bars") or [],key=lambda x:x["t"]); prev=e["prev_close"]
    prior_pct=prior_ts=None; streak=0; positive_total=eligible_usable=0
    prearm=first10=first30=None
    for b in bars:
        close=float(b.get("c") or 0); high=float(b.get("h") or 0); vol=float(b.get("v") or 0)
        if close<=0 or high<=0: continue
        ts=datetime.fromisoformat(b["t"].replace("Z","+00:00"))
        pct=(close/prev-1)*100; hp=(high/prev-1)*100
        if first10 is None and hp>=10: first10=ts
        if first30 is None and hp>=30: first30=ts
        eligible=first30 is None
        accel=None
        if prior_ts is not None:
            dt=(ts-prior_ts).total_seconds()/60
            if dt>0 and dt<=max_gap:
                accel=(pct-prior_pct)/dt
            elif dt>max_gap:
                streak=0
        interval_eligible=eligible and accel is not None and 0<pct<10
        if interval_eligible: eligible_usable+=1
        positive=interval_eligible and accel>0 and vol>0
        if positive:
            positive_total+=1; streak+=1
        else:
            streak=0
        if eligible and prearm is None and 0<pct<10 and streak>=2: prearm=ts
        prior_pct,prior_ts=pct,ts
    path_observable=eligible_usable>=2
    if prearm is not None: miss="DETECTED"
    elif not path_observable: miss="PATH_UNOBSERVABLE"
    elif positive_total>=2: miss="PERSISTENCE_MISS"
    else: miss="FLOW_MISS"
    return {**e,"flow_prearm":prearm is not None,"flow_prearm_ts":prearm.isoformat() if prearm else None,
      "path_observable":path_observable,"miss_class":miss,
      "first10_ts":first10.isoformat() if first10 else None,
      "first30_ts":first30.isoformat() if first30 else None,
      "first30_before_0930_et":bool(first30 and first30.astimezone(ET).time()<dtime(9,30))}

def news_one(e,headers):
    d=datetime.fromisoformat(e["date"]).replace(tzinfo=ET)
    start=(d-timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0)
    cutoff=datetime.fromisoformat(e["first10_ts"]) if e.get("first10_ts") else d.replace(hour=20,minute=0,second=0,microsecond=0)
    payload=request_json_resilient("/v1beta1/news",{
      "symbols":e["symbol"],"start":start.isoformat(),"end":cutoff.isoformat(),
      "limit":50,"sort":"asc","include_content":"false"},headers)
    hits=[]
    for n in payload.get("news") or []:
        raw=n.get("created_at")
        if not raw: continue
        ts=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if ts>=cutoff.astimezone(timezone.utc): continue
        text=((n.get("headline") or "")+" "+(n.get("summary") or "")).lower()
        cats=sorted(cat for cat,words in CATALYSTS.items() if any(word in text for word in words))
        if cats:
            hits.append({"created_at":ts.isoformat(),"categories":cats,"headline":n.get("headline")})
    earliest=min((datetime.fromisoformat(x["created_at"]) for x in hits),default=None)
    first30=datetime.fromisoformat(e["first30_ts"]) if e.get("first30_ts") else None
    lead=(first30-earliest).total_seconds()/60 if earliest and first30 else None
    return {**e,"event_discovery":bool(hits),"event_ts":earliest.isoformat() if earliest else None,
      "event_categories":sorted({c for x in hits for c in x["categories"]}),
      "event_hit_count":len(hits),"event_lead30_min":lead,
      "event_headlines":hits[:5]}

def summarize(win,non):
    w=len(win); n=len(non)
    ew=sum(x["event_discovery"] for x in win); en=sum(x["event_discovery"] for x in non)
    fw=sum(x["flow_prearm"] for x in win); fn=sum(x["flow_prearm"] for x in non)
    cw=sum(x["event_discovery"] or x["flow_prearm"] for x in win)
    cn=sum(x["event_discovery"] or x["flow_prearm"] for x in non)
    pu=[x for x in win if x["miss_class"]=="PATH_UNOBSERVABLE"]
    pre=[x for x in win if x["first30_before_0930_et"]]
    overlap_w=sum(x["event_discovery"] and x["flow_prearm"] for x in win)
    return {"winner_count":w,"nonwinner_count":n,
      "flow_winner_recall":fw/w if w else None,
      "flow_nonwinner_false_positive_rate":fn/n if n else None,
      "event_winner_recall":ew/w if w else None,
      "event_path_unobservable_winner_recall":sum(x["event_discovery"] for x in pu)/len(pu) if pu else None,
      "event_path_unobservable_winner_count":sum(x["event_discovery"] for x in pu),
      "path_unobservable_winner_count":len(pu),
      "event_nonwinner_false_positive_rate":en/n if n else None,
      "event_precision_to_30":ew/(ew+en) if ew+en else None,
      "median_event_lead30_min":median([x["event_lead30_min"] for x in win]),
      "flow_event_overlap_winners":overlap_w,
      "event_incremental_winners_over_flow":sum(x["event_discovery"] and not x["flow_prearm"] for x in win),
      "combined_winner_recall":cw/w if w else None,
      "combined_nonwinner_false_positive_rate":cn/n if n else None,
      "combined_precision_to_30":cw/(cw+cn) if cw+cn else None,
      "preopen30_winner_count":len(pre),
      "preopen30_event_coverage":sum(x["event_discovery"] for x in pre)/len(pre) if pre else None,
      "preopen30_event_count":sum(x["event_discovery"] for x in pre)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--universe",default="config/universe.csv");p.add_argument("--out",default="research/fast_path_v044_event.json")
    p.add_argument("--winners",type=int,default=300);p.add_argument("--nonwinners",type=int,default=300);p.add_argument("--lookback-days",type=int,default=240)
    p.add_argument("--feed",default="iex");p.add_argument("--workers",type=int,default=2);a=p.parse_args()
    h={"APCA-API-KEY-ID":os.environ["ALPACA_API_KEY"],"APCA-API-SECRET-KEY":os.environ["ALPACA_SECRET_KEY"]}
    end=datetime.now(timezone.utc);start=end-timedelta(days=a.lookback_days)
    dm=daily(load_universe(a.universe),start.isoformat(),end.isoformat(),h,a.feed)
    winners,non=sessions(dm);winners=winners[:a.winners];non=non[:a.nonwinners]
    def run_path(rows):
        out=[]
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            fs=[pool.submit(path_one,e,h,a.feed) for e in rows]
            for f in as_completed(fs):out.append(f.result())
        return out
    def run_news(rows):
        out=[]
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            fs=[pool.submit(news_one,e,h) for e in rows]
            for f in as_completed(fs):out.append(f.result())
        return out
    wr=run_news(run_path(winners)); nr=run_news(run_path(non)); s=summarize(wr,nr)
    gates={"combined_recall_ge_35pct_research_comparator":s["combined_winner_recall"]>=.35,
      "combined_precision_ge_8pct_research_comparator":s["combined_precision_to_30"]>=.08,
      "historical_only_no_promotion":True}
    payload={"status":"CALIBRATION_ONLY","version":"v0.4.4-BALANCED-EVENT-COVERAGE-SHADOW",
      "authoritative":False,"buy":False,"generated_at":datetime.now(timezone.utc).isoformat(),
      "summary":s,"research_comparators":gates,
      "limitations":["retrospective/in-sample","current-universe survivorship bias","IEX partial-market coverage","Alpaca news coverage is not exhaustive","keyword EVENT classifier is research-only","bar/news replay cannot prove fills"],
      "winners":wr,"nonwinners":nr}
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10))
    print(json.dumps({"summary":s,"research_comparators":gates},sort_keys=True))
if __name__=="__main__":main()
