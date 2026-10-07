"""SAG-30 v0.4.6 FLOW pair-progress DEV/HOLDOUT study.
Research-only. EVENT unchanged. v0.3.3 FROZEN unchanged. Never BUY.
"""
import argparse,gzip,json
from datetime import datetime,time as dtime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import median

ET=ZoneInfo("America/New_York")
DATASET_SHA="22891b1f8148bd0616abee603c196b453c229350c185452bb937e9da50b780ff"
DEV_DATES={"2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-25"}
HOLDOUT_DATES={"2026-09-28","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"}
GRID=[0.10,0.20,0.35,0.50,0.75,1.00,1.50,2.00]
CATALYSTS={
 "ANTI_DILUTION_BUYBACK":("buyback","repurchase","at-the-market","atm","suspend"),
 "MNA":("merger","acquisition","acquire","strategic combination","business combination"),
 "CONTRACT":("contract","agreement","award","order","purchase order","customer"),
 "FDA_CLINICAL":("fda","clinical","trial","phase 1","phase 2","phase 3","topline"),
 "GOV_DEFENSE":("department of defense","dod","government","federal","army","navy","air force","grant"),
 "EARNINGS":("earnings","results","revenue","guidance"),
 "PATENT_TECH":("patent","technology","platform","artificial intelligence","blockchain"),
}

def score_one(e,bars,news,max_gap=5.0):
    prev=e["prev_close"];prior_pct=prior_ts=None;streak=0;streak_start_pct=None
    prearm=first10=first30=None;pair_progress=None
    for b in sorted(bars,key=lambda x:x["t"]):
        close=float(b.get("c") or 0);high=float(b.get("h") or 0);vol=float(b.get("v") or 0)
        if close<=0 or high<=0:continue
        ts=datetime.fromisoformat(b["t"].replace("Z","+00:00"));pct=(close/prev-1)*100;hp=(high/prev-1)*100
        if first10 is None and hp>=10:first10=ts
        if first30 is None and hp>=30:first30=ts
        eligible=first30 is None;accel=None
        if prior_ts is not None:
            dt=(ts-prior_ts).total_seconds()/60
            if 0<dt<=max_gap:accel=(pct-prior_pct)/dt
            elif dt>max_gap:
                streak=0;streak_start_pct=None
        interval_eligible=eligible and accel is not None and 0<pct<10
        positive=interval_eligible and accel>0 and vol>0
        if positive:
            if streak==0:streak_start_pct=prior_pct
            streak+=1
        else:
            streak=0;streak_start_pct=None
        if eligible and prearm is None and 0<pct<10 and streak>=2:
            prearm=ts
            pair_progress=(pct-streak_start_pct) if streak_start_pct is not None else None
        prior_pct,prior_ts=pct,ts

    day=datetime.fromisoformat(e["date"]).replace(tzinfo=ET)
    start=(day-timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0)
    cutoff=first10 if first10 else day.replace(hour=20,minute=0,second=0,microsecond=0)
    hits=[]
    for n in news:
        raw=n.get("created_at")
        if not raw:continue
        ts=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if not(start.astimezone(ts.tzinfo)<=ts<cutoff.astimezone(ts.tzinfo)):continue
        text=((n.get("headline") or "")+" "+(n.get("summary") or "")).lower()
        cats=[cat for cat,words in CATALYSTS.items() if any(w in text for w in words)]
        if cats:hits.append(ts)
    event_ts=min(hits,default=None)
    return {**e,"event_discovery":event_ts is not None,"event_ts":event_ts.isoformat() if event_ts else None,
      "flow_prearm":prearm is not None,"flow_prearm_ts":prearm.isoformat() if prearm else None,
      "pair_progress_pp":pair_progress,"first30_ts":first30.isoformat() if first30 else None}

def metrics(rows,threshold=None):
    w=[x for x in rows if x["label"]=="winner"];n=[x for x in rows if x["label"]=="nonwinner"]
    def flow(x):
        if not x["flow_prearm"]:return False
        if threshold is None:return True
        return x["pair_progress_pp"] is not None and x["pair_progress_pp"]>=threshold
    def union(x):return x["event_discovery"] or flow(x)
    ew=sum(x["event_discovery"] for x in w);en=sum(x["event_discovery"] for x in n)
    fw=sum(flow(x) for x in w);fn=sum(flow(x) for x in n)
    cw=sum(union(x) for x in w);cn=sum(union(x) for x in n)
    overlap=sum(x["event_discovery"] and flow(x) for x in w)
    flow_only=sum(flow(x) and not x["event_discovery"] for x in w)
    leads=[]
    for x in w:
        sig=[]
        if x["event_discovery"]:sig.append(datetime.fromisoformat(x["event_ts"]))
        if flow(x):sig.append(datetime.fromisoformat(x["flow_prearm_ts"]))
        if sig and x["first30_ts"]:
            leads.append((datetime.fromisoformat(x["first30_ts"])-min(sig)).total_seconds()/60)
    return {"winner_count":len(w),"nonwinner_count":len(n),"threshold":threshold,
      "event_winner_recall":ew/len(w),"event_nonwinner_fpr":en/len(n),
      "flow_winner_recall":fw/len(w),"flow_nonwinner_fpr":fn/len(n),
      "combined_winner_recall":cw/len(w),"combined_nonwinner_fpr":cn/len(n),
      "combined_precision":cw/(cw+cn) if cw+cn else None,
      "flow_event_overlap_winners":overlap,"flow_incremental_winners_over_event":flow_only,
      "median_combined_lead30_min":median(leads)}

def eligible(m):
    return m["combined_winner_recall"]>=.35 and m["combined_precision"]>=.08 and (m["median_combined_lead30_min"] or -1)>=3

def main():
    p=argparse.ArgumentParser();p.add_argument("--dataset",default="research/cache/sag30_date_matched_v045_dataset.json.gz");p.add_argument("--out",default="research/fast_path_v046_pair_progress.json");a=p.parse_args()
    with gzip.open(a.dataset,"rt",encoding="utf-8") as f:d=json.load(f)
    if d.get("dataset_sha256")!=DATASET_SHA:raise SystemExit("dataset hash mismatch")
    scored=[]
    for e in d["cohort"]:
        k=f'{e["date"]}|{e["symbol"]}';scored.append(score_one(e,d["bars"].get(k,[]),d["news"].get(k,[])))
    dates={x["date"] for x in scored}
    if dates != DEV_DATES|HOLDOUT_DATES:raise SystemExit(f"unexpected dates {sorted(dates)}")
    # Exact date matching assertion.
    for date in sorted(dates):
        wc=sum(x["label"]=="winner" and x["date"]==date for x in scored)
        nc=sum(x["label"]=="nonwinner" and x["date"]==date for x in scored)
        if wc!=nc or wc==0:raise SystemExit(f"date mismatch {date}: {wc}/{nc}")
    dev=[x for x in scored if x["date"] in DEV_DATES];hold=[x for x in scored if x["date"] in HOLDOUT_DATES]
    if (sum(x["label"]=="winner" for x in dev),sum(x["label"]=="nonwinner" for x in dev))!=(149,149):raise SystemExit("DEV count mismatch")
    if (sum(x["label"]=="winner" for x in hold),sum(x["label"]=="nonwinner" for x in hold))!=(151,151):raise SystemExit("HOLDOUT count mismatch")

    dev_base=metrics(dev,None); candidates=[]
    for th in GRID:
        m=metrics(dev,th);m["eligible"]=eligible(m);candidates.append(m)
    ok=[m for m in candidates if m["eligible"]]
    selected=None
    if ok:
        selected=sorted(ok,key=lambda m:(m["combined_nonwinner_fpr"],-m["combined_winner_recall"],-m["combined_precision"],m["threshold"]))[0]["threshold"]
    hold_base=metrics(hold,None)
    hold_selected=metrics(hold,selected) if selected is not None else None
    hold_pass=False
    if hold_selected:
        hold_pass=(eligible(hold_selected) and
          (hold_base["combined_nonwinner_fpr"]-hold_selected["combined_nonwinner_fpr"])>=.05)
    payload={"version":"v0.4.6-FLOW-PAIR-PROGRESS-SHADOW","status":"RESEARCH_ONLY","buy":False,
      "dataset_sha256":DATASET_SHA,"split":{"dev_dates":sorted(DEV_DATES),"holdout_dates":sorted(HOLDOUT_DATES),
      "dev_class_count":149,"holdout_class_count":151},
      "grid":GRID,"dev_baseline":dev_base,"dev_candidates":candidates,"selected_threshold":selected,
      "holdout_baseline":hold_base,"holdout_selected":hold_selected,"holdout_pass":hold_pass,
      "decision":"PASS" if hold_pass else "FAIL","rows_feature_audit":scored}
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10))
    print(json.dumps({k:payload[k] for k in ("selected_threshold","dev_baseline","holdout_baseline","holdout_selected","holdout_pass","decision")},sort_keys=True))
if __name__=="__main__":main()
