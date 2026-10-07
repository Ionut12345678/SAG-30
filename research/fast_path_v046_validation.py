"""Validate frozen v0.4.6 FLOW activity gate on an independent date-matched cohort."""
import argparse,gzip,json,statistics
from datetime import datetime,time as dtime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import median
from research.fast_path_v045_date_matched import CATALYSTS

ET=ZoneInfo("America/New_York")

def score_one(e,bars,news,max_gap=5.0):
    prev=e["prev_close"];prior_pct=prior_ts=None;streak=0;hist_vol=[];prearm=first10=first30=None;activity_ratio=None
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
            elif dt>max_gap:streak=0
        positive=eligible and accel is not None and 0<pct<10 and accel>0 and vol>0
        streak=streak+1 if positive else 0
        if eligible and prearm is None and 0<pct<10 and streak>=2:
            prearm=ts
            if hist_vol:
                base=statistics.median(hist_vol[-20:])
                activity_ratio=(vol/base) if base>0 else None
        hist_vol.append(vol);prior_pct,prior_ts=pct,ts
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
    event=bool(hits);event_ts=min(hits) if hits else None
    return {**e,"event_discovery":event,"base_flow":bool(prearm),
      "activity_ratio_at_prearm":activity_ratio,
      "filtered_flow":bool(prearm and activity_ratio is not None and activity_ratio>=1.50),
      "event_lead30_min":(first30-event_ts).total_seconds()/60 if first30 and event_ts else None,
      "preopen30":bool(first30 and first30.astimezone(ET).time()<dtime(9,30))}

def metrics(rows,flowkey):
    w=[x for x in rows if x["label"]=="winner"];n=[x for x in rows if x["label"]=="nonwinner"]
    ew=sum(x["event_discovery"] for x in w);en=sum(x["event_discovery"] for x in n)
    fw=sum(x[flowkey] for x in w);fn=sum(x[flowkey] for x in n)
    cw=sum(x["event_discovery"] or x[flowkey] for x in w);cn=sum(x["event_discovery"] or x[flowkey] for x in n)
    return {"event_winners":ew,"event_nonwinners":en,"flow_winners":fw,"flow_nonwinners":fn,
      "combined_winners":cw,"combined_nonwinners":cn,
      "combined_recall":cw/len(w),"combined_fpr":cn/len(n),"combined_precision":cw/(cw+cn) if cw+cn else None,
      "flow_only_winners":sum(x[flowkey] and not x["event_discovery"] for x in w),
      "flow_only_nonwinners":sum(x[flowkey] and not x["event_discovery"] for x in n),
      "median_event_lead30_min":median([x["event_lead30_min"] for x in w])}

def main():
    p=argparse.ArgumentParser();p.add_argument("--dataset",default="research/cache/sag30_v046_validation_dataset.json.gz");p.add_argument("--out",default="research/fast_path_v046_validation.json");a=p.parse_args()
    with gzip.open(a.dataset,"rt",encoding="utf-8") as f:d=json.load(f)
    rows=[]
    for e in d["cohort"]:
        k=f'{e["date"]}|{e["symbol"]}';rows.append(score_one(e,d["bars"].get(k,[]),d["news"].get(k,[])))
    base=metrics(rows,"base_flow");filt=metrics(rows,"filtered_flow")
    fpr_reduction=(base["combined_fpr"]-filt["combined_fpr"])/base["combined_fpr"] if base["combined_fpr"] else None
    gates={"combined_recall_ge_35pct":filt["combined_recall"]>=.35,
      "combined_precision_ge_8pct":filt["combined_precision"]>=.08,
      "combined_fpr_relative_reduction_ge_25pct":fpr_reduction is not None and fpr_reduction>=.25,
      "historical_only_no_promotion":True}
    payload={"version":"v0.4.6-FLOW-ACTIVITY-GATE-SHADOW","status":"VALIDATION_ONLY","buy":False,
      "dataset_sha256":d["dataset_sha256"],"threshold_activity_ratio":1.50,
      "baseline_unfiltered":base,"v046_filtered":filt,"combined_fpr_relative_reduction":fpr_reduction,
      "gates":gates,"rows":rows}
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10));print(json.dumps({k:payload[k] for k in ("baseline_unfiltered","v046_filtered","combined_fpr_relative_reduction","gates")},sort_keys=True))
if __name__=="__main__":main()
