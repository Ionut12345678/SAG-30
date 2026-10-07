"""SAG-30 v0.4.7 causal activity-impulse FLOW filter.
Research-only DEV/HOLDOUT. EVENT unchanged. Never BUY.
"""
import argparse,gzip,json,statistics
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import median

ET=ZoneInfo("America/New_York")
DATASET_SHA="22891b1f8148bd0616abee603c196b453c229350c185452bb937e9da50b780ff"
DEV_DATES={"2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-25"}
HOLDOUT_DATES={"2026-09-28","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"}
GRID=[1.00,1.25,1.50,2.00,3.00,5.00]
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
    prev=e["prev_close"];prior_pct=prior_ts=None;streak=0;prearm=first10=first30=None
    hist_vol=[];pair_vols=[];pair_base=None;activity_impulse=None
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
                streak=0;pair_vols=[];pair_base=None
        interval_eligible=eligible and accel is not None and 0<pct<10
        positive=interval_eligible and accel>0 and vol>0
        if positive:
            if streak==0:
                prior=hist_vol[-20:]
                pair_base=statistics.median(prior) if len(prior)>=5 else None
                pair_vols=[vol]
            else:pair_vols.append(vol)
            streak+=1
        else:
            streak=0;pair_vols=[];pair_base=None
        if eligible and prearm is None and 0<pct<10 and streak>=2:
            prearm=ts
            if pair_base is not None and pair_base>0:
                activity_impulse=sum(pair_vols[-2:])/2/pair_base
        hist_vol.append(vol)
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
        txt=((n.get("headline") or "")+" "+(n.get("summary") or "")).lower()
        if any(any(word in txt for word in words) for words in CATALYSTS.values()):hits.append(ts)
    event_ts=min(hits,default=None)
    return {**e,"event_discovery":event_ts is not None,"event_ts":event_ts.isoformat() if event_ts else None,
      "flow_prearm":prearm is not None,"flow_prearm_ts":prearm.isoformat() if prearm else None,
      "activity_impulse":activity_impulse,"first30_ts":first30.isoformat() if first30 else None}

def metrics(rows,threshold=None):
    w=[x for x in rows if x["label"]=="winner"];n=[x for x in rows if x["label"]=="nonwinner"]
    def flow(x):
        if not x["flow_prearm"]:return False
        if threshold is None:return True
        return x["activity_impulse"] is not None and x["activity_impulse"]>=threshold
    def union(x):return x["event_discovery"] or flow(x)
    fw=sum(flow(x) for x in w);fn=sum(flow(x) for x in n);cw=sum(union(x) for x in w);cn=sum(union(x) for x in n)
    leads=[]
    for x in w:
        sig=[]
        if x["event_discovery"]:sig.append(datetime.fromisoformat(x["event_ts"]))
        if flow(x):sig.append(datetime.fromisoformat(x["flow_prearm_ts"]))
        if sig and x["first30_ts"]:leads.append((datetime.fromisoformat(x["first30_ts"])-min(sig)).total_seconds()/60)
    return {"winner_count":len(w),"nonwinner_count":len(n),"threshold":threshold,
      "event_winner_recall":sum(x["event_discovery"] for x in w)/len(w),
      "event_nonwinner_fpr":sum(x["event_discovery"] for x in n)/len(n),
      "flow_winner_recall":fw/len(w),"flow_nonwinner_fpr":fn/len(n),
      "combined_winner_recall":cw/len(w),"combined_nonwinner_fpr":cn/len(n),
      "combined_precision":cw/(cw+cn) if cw+cn else None,
      "flow_incremental_winners_over_event":sum(flow(x) and not x["event_discovery"] for x in w),
      "flow_event_overlap_winners":sum(flow(x) and x["event_discovery"] for x in w),
      "activity_unknown_flow_winners":sum(x["flow_prearm"] and x["activity_impulse"] is None for x in w),
      "activity_unknown_flow_nonwinners":sum(x["flow_prearm"] and x["activity_impulse"] is None for x in n),
      "median_combined_lead30_min":median(leads)}

def main():
    p=argparse.ArgumentParser();p.add_argument("--dataset",default="research/cache/sag30_date_matched_v045_dataset.json.gz");p.add_argument("--out",default="research/fast_path_v047_activity_impulse.json");a=p.parse_args()
    with gzip.open(a.dataset,"rt",encoding="utf-8") as f:d=json.load(f)
    if d.get("dataset_sha256")!=DATASET_SHA:raise SystemExit("dataset hash mismatch")
    rows=[]
    for e in d["cohort"]:
        k=f'{e["date"]}|{e["symbol"]}';rows.append(score_one(e,d["bars"].get(k,[]),d["news"].get(k,[])))
    dates=DEV_DATES|HOLDOUT_DATES
    if {x["date"] for x in rows}!=dates:raise SystemExit("date set mismatch")
    for date in sorted(dates):
        wc=sum(x["label"]=="winner" and x["date"]==date for x in rows);nc=sum(x["label"]=="nonwinner" and x["date"]==date for x in rows)
        if wc!=nc or wc==0:raise SystemExit(f"date mismatch {date} {wc}/{nc}")
    dev=[x for x in rows if x["date"] in DEV_DATES];hold=[x for x in rows if x["date"] in HOLDOUT_DATES]
    dev_base=metrics(dev,None);hold_base=metrics(hold,None)
    floor=.90*dev_base["combined_winner_recall"]
    cand=[]
    for th in GRID:
        m=metrics(dev,th)
        m["eligible"]=(m["combined_winner_recall"]>=floor and m["combined_precision"]>=.08 and
          (m["median_combined_lead30_min"] or -1)>=3 and
          dev_base["combined_nonwinner_fpr"]-m["combined_nonwinner_fpr"]>=.03)
        cand.append(m)
    ok=[m for m in cand if m["eligible"]]
    selected=sorted(ok,key=lambda m:(m["combined_nonwinner_fpr"],-m["combined_winner_recall"],-m["combined_precision"],m["threshold"]))[0]["threshold"] if ok else None
    hold_sel=metrics(hold,selected) if selected is not None else None
    passed=bool(hold_sel and hold_sel["combined_winner_recall"]>=.35 and hold_sel["combined_precision"]>=.08 and
      (hold_sel["median_combined_lead30_min"] or -1)>=3 and hold_base["combined_nonwinner_fpr"]-hold_sel["combined_nonwinner_fpr"]>=.05)
    payload={"version":"v0.4.7-CAUSAL-ACTIVITY-IMPULSE-SHADOW","status":"RESEARCH_ONLY","buy":False,
      "dataset_sha256":DATASET_SHA,"dev_recall_floor":floor,"grid":GRID,
      "dev_baseline":dev_base,"dev_candidates":cand,"selected_threshold":selected,
      "holdout_baseline":hold_base,"holdout_selected":hold_sel,"holdout_pass":passed,
      "decision":"PASS" if passed else "FAIL","rows_feature_audit":rows}
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10))
    print(json.dumps({k:payload[k] for k in ("dev_recall_floor","selected_threshold","dev_baseline","holdout_baseline","holdout_selected","holdout_pass","decision")},sort_keys=True))
if __name__=="__main__":main()
