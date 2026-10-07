"""Score frozen date-matched SAG-30 dataset with unchanged v0.4.4 EVENT+FLOW semantics."""
import argparse,gzip,json
from datetime import datetime,time as dtime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import median

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

def score_one(e,bars,news,max_gap=5.0):
    prev=e["prev_close"];prior_pct=prior_ts=None;streak=0;positive_total=eligible_usable=0
    prearm=first10=first30=None
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
        interval_eligible=eligible and accel is not None and 0<pct<10
        if interval_eligible:eligible_usable+=1
        positive=interval_eligible and accel>0 and vol>0
        if positive:positive_total+=1;streak+=1
        else:streak=0
        if eligible and prearm is None and 0<pct<10 and streak>=2:prearm=ts
        prior_pct,prior_ts=pct,ts
    path_observable=eligible_usable>=2
    miss="DETECTED" if prearm else ("PATH_UNOBSERVABLE" if not path_observable else ("PERSISTENCE_MISS" if positive_total>=2 else "FLOW_MISS"))
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
        cats=sorted(cat for cat,words in CATALYSTS.items() if any(w in text for w in words))
        if cats:hits.append((ts,cats))
    event=bool(hits);event_ts=min((x[0] for x in hits),default=None)
    lead=(first30-event_ts).total_seconds()/60 if first30 and event_ts else None
    return {**e,"flow_prearm":bool(prearm),"event_discovery":event,"event_lead30_min":lead,
      "path_observable":path_observable,"miss_class":miss,
      "first30_before_0930_et":bool(first30 and first30.astimezone(ET).time()<dtime(9,30))}

def summary(w,n):
    def cnt(rows,p):return sum(1 for x in rows if p(x))
    ew=cnt(w,lambda x:x["event_discovery"]);en=cnt(n,lambda x:x["event_discovery"])
    fw=cnt(w,lambda x:x["flow_prearm"]);fn=cnt(n,lambda x:x["flow_prearm"])
    cw=cnt(w,lambda x:x["event_discovery"] or x["flow_prearm"]);cn=cnt(n,lambda x:x["event_discovery"] or x["flow_prearm"])
    pu=[x for x in w if x["miss_class"]=="PATH_UNOBSERVABLE"];pre=[x for x in w if x["first30_before_0930_et"]]
    return {"winner_count":len(w),"nonwinner_count":len(n),
      "event_winner_recall":ew/len(w),"event_nonwinner_false_positive_rate":en/len(n),"event_precision_to_30":ew/(ew+en) if ew+en else None,
      "flow_winner_recall":fw/len(w),"flow_nonwinner_false_positive_rate":fn/len(n),"flow_precision_to_30":fw/(fw+fn) if fw+fn else None,
      "combined_winner_recall":cw/len(w),"combined_nonwinner_false_positive_rate":cn/len(n),"combined_precision_to_30":cw/(cw+cn) if cw+cn else None,
      "event_incremental_winners_over_flow":cnt(w,lambda x:x["event_discovery"] and not x["flow_prearm"]),
      "flow_event_overlap_winners":cnt(w,lambda x:x["event_discovery"] and x["flow_prearm"]),
      "path_unobservable_winner_count":len(pu),"event_path_unobservable_winner_count":cnt(pu,lambda x:x["event_discovery"]),
      "preopen30_winner_count":len(pre),"preopen30_event_count":cnt(pre,lambda x:x["event_discovery"]),
      "median_event_lead30_min":median([x["event_lead30_min"] for x in w])}

def main():
    p=argparse.ArgumentParser();p.add_argument("--dataset",default="research/cache/sag30_date_matched_v045_dataset.json.gz");p.add_argument("--out",default="research/fast_path_v045_date_matched.json");a=p.parse_args()
    with gzip.open(a.dataset,"rt",encoding="utf-8") as f:d=json.load(f)
    scored=[]
    for e in d["cohort"]:
        k=f'{e["date"]}|{e["symbol"]}';scored.append(score_one(e,d["bars"].get(k,[]),d["news"].get(k,[])))
    w=[x for x in scored if x["label"]=="winner"];n=[x for x in scored if x["label"]=="nonwinner"];s=summary(w,n)
    gates={"combined_recall_ge_35pct":s["combined_winner_recall"]>=.35,"combined_precision_ge_8pct":s["combined_precision_to_30"]>=.08,
      "historical_only_no_promotion":True}
    payload={"version":"v0.4.5-DATE-MATCHED-BASELINE-SHADOW","status":"EVALUATION_ONLY","buy":False,
      "dataset_sha256":d["dataset_sha256"],"summary":s,"research_comparators":gates,"rows":scored}
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10));print(json.dumps({"summary":s,"research_comparators":gates},sort_keys=True))
if __name__=="__main__":main()
