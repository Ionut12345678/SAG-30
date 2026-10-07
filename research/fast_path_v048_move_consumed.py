"""SAG-30 v0.4.8 FLOW move-consumed floor DEV/HOLDOUT study. Research only."""
import argparse,gzip,json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import median
ET=ZoneInfo("America/New_York")
DATASET_SHA="22891b1f8148bd0616abee603c196b453c229350c185452bb937e9da50b780ff"
DEV={"2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-25"}
HOLD={"2026-09-28","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"}
GRID=[.5,1.,2.,3.,4.,5.]
CATS={
 "ANTI_DILUTION_BUYBACK":("buyback","repurchase","at-the-market","atm","suspend"),"MNA":("merger","acquisition","acquire","strategic combination","business combination"),
 "CONTRACT":("contract","agreement","award","order","purchase order","customer"),"FDA_CLINICAL":("fda","clinical","trial","phase 1","phase 2","phase 3","topline"),
 "GOV_DEFENSE":("department of defense","dod","government","federal","army","navy","air force","grant"),"EARNINGS":("earnings","results","revenue","guidance"),
 "PATENT_TECH":("patent","technology","platform","artificial intelligence","blockchain")}

def one(e,bars,news):
 prev=e["prev_close"];prior_pct=prior_ts=None;streak=0;prearm=first10=first30=None;move=None
 for b in sorted(bars,key=lambda x:x["t"]):
  c=float(b.get("c") or 0);h=float(b.get("h") or 0);v=float(b.get("v") or 0)
  if c<=0 or h<=0:continue
  ts=datetime.fromisoformat(b["t"].replace("Z","+00:00"));pct=(c/prev-1)*100;hp=(h/prev-1)*100
  if first10 is None and hp>=10:first10=ts
  if first30 is None and hp>=30:first30=ts
  accel=None
  if prior_ts is not None:
   dt=(ts-prior_ts).total_seconds()/60
   if 0<dt<=5:accel=(pct-prior_pct)/dt
   elif dt>5:streak=0
  pos=first30 is None and accel is not None and 0<pct<10 and accel>0 and v>0
  streak=streak+1 if pos else 0
  if prearm is None and first30 is None and 0<pct<10 and streak>=2:prearm=ts;move=pct
  prior_pct,prior_ts=pct,ts
 day=datetime.fromisoformat(e["date"]).replace(tzinfo=ET);start=(day-timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0)
 cutoff=first10 if first10 else day.replace(hour=20,minute=0,second=0,microsecond=0);hits=[]
 for n in news:
  raw=n.get("created_at")
  if not raw:continue
  ts=datetime.fromisoformat(raw.replace("Z","+00:00"))
  if not(start.astimezone(ts.tzinfo)<=ts<cutoff.astimezone(ts.tzinfo)):continue
  txt=((n.get("headline") or "")+" "+(n.get("summary") or "")).lower()
  if any(any(w in txt for w in words) for words in CATS.values()):hits.append(ts)
 ev=min(hits,default=None)
 return {**e,"event_discovery":ev is not None,"event_ts":ev.isoformat() if ev else None,"flow_prearm":prearm is not None,
  "flow_prearm_ts":prearm.isoformat() if prearm else None,"move_consumed_pp":move,"first30_ts":first30.isoformat() if first30 else None}

def met(rows,th=None):
 w=[x for x in rows if x["label"]=="winner"];n=[x for x in rows if x["label"]=="nonwinner"]
 def fl(x):return x["flow_prearm"] and (th is None or (x["move_consumed_pp"] is not None and x["move_consumed_pp"]>=th))
 def un(x):return x["event_discovery"] or fl(x)
 fw=sum(fl(x) for x in w);fn=sum(fl(x) for x in n);cw=sum(un(x) for x in w);cn=sum(un(x) for x in n);leads=[]
 for x in w:
  sig=[]
  if x["event_discovery"]:sig.append(datetime.fromisoformat(x["event_ts"]))
  if fl(x):sig.append(datetime.fromisoformat(x["flow_prearm_ts"]))
  if sig and x["first30_ts"]:leads.append((datetime.fromisoformat(x["first30_ts"])-min(sig)).total_seconds()/60)
 return {"threshold":th,"winner_count":len(w),"nonwinner_count":len(n),"flow_winner_recall":fw/len(w),"flow_nonwinner_fpr":fn/len(n),
  "combined_winner_recall":cw/len(w),"combined_nonwinner_fpr":cn/len(n),"combined_precision":cw/(cw+cn) if cw+cn else None,
  "flow_incremental_winners_over_event":sum(fl(x) and not x["event_discovery"] for x in w),
  "flow_event_overlap_winners":sum(fl(x) and x["event_discovery"] for x in w),"median_combined_lead30_min":median(leads)}

def main():
 p=argparse.ArgumentParser();p.add_argument("--dataset",default="research/cache/sag30_date_matched_v045_dataset.json.gz");p.add_argument("--out",default="research/fast_path_v048_move_consumed.json");a=p.parse_args()
 with gzip.open(a.dataset,"rt") as f:d=json.load(f)
 if d.get("dataset_sha256")!=DATASET_SHA:raise SystemExit("dataset hash mismatch")
 rows=[]
 for e in d["cohort"]:
  k=f'{e["date"]}|{e["symbol"]}';rows.append(one(e,d["bars"].get(k,[]),d["news"].get(k,[])))
 dev=[x for x in rows if x["date"] in DEV];hold=[x for x in rows if x["date"] in HOLD]
 base=met(dev);hb=met(hold);floor=.9*base["combined_winner_recall"];cand=[]
 for th in GRID:
  m=met(dev,th);m["eligible"]=(m["combined_winner_recall"]>=floor and m["combined_precision"]>=.08 and (m["median_combined_lead30_min"] or -1)>=3 and base["combined_nonwinner_fpr"]-m["combined_nonwinner_fpr"]>=.03);cand.append(m)
 ok=[x for x in cand if x["eligible"]];sel=sorted(ok,key=lambda x:(x["combined_nonwinner_fpr"],-x["combined_winner_recall"],-x["combined_precision"],x["threshold"]))[0]["threshold"] if ok else None
 hs=met(hold,sel) if sel is not None else None
 passed=bool(hs and hs["combined_winner_recall"]>=.35 and hs["combined_precision"]>=.08 and (hs["median_combined_lead30_min"] or -1)>=3 and hb["combined_nonwinner_fpr"]-hs["combined_nonwinner_fpr"]>=.05)
 out={"version":"v0.4.8-FLOW-MOVE-CONSUMED-FLOOR-SHADOW","status":"RESEARCH_ONLY","buy":False,"dataset_sha256":DATASET_SHA,"dev_recall_floor":floor,
  "grid":GRID,"dev_baseline":base,"dev_candidates":cand,"selected_threshold":sel,"holdout_baseline":hb,"holdout_selected":hs,"holdout_pass":passed,"decision":"PASS" if passed else "FAIL","rows_feature_audit":rows}
 Path(a.out).write_text(json.dumps(out,indent=2,sort_keys=True)+chr(10));print(json.dumps({k:out[k] for k in ("selected_threshold","dev_baseline","holdout_baseline","holdout_selected","holdout_pass","decision")},sort_keys=True))
if __name__=="__main__":main()
