"""SHADOW union replay of fixed pre-specified rank rules at first eligible snapshot.

Union is computed prospectively per observation. No training on outcomes, no BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def compare(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 groups=defaultdict(list)
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,selected,
 rank_change,rank_acceleration,rank_impulse,rank_turnover
 FROM scout_history ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups[(r["session"],r["symbol"])].append(r)
 cohort=[]
 for rows in groups.values():
  idx=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if idx is None:continue
  r=rows[idx]
  later=[x for x in rows[idx+1:] if x["retrieval_ts"]>r["retrieval_ts"]]
  if not later:continue
  cohort.append((r,{t:any(x["change_pct"]>=t for x in later) for t in (30,50)}))
 rules={
 "baseline":lambda r:bool(r["selected"]),
 "turnover20":lambda r:r["rank_turnover"]<=20,
 "turnover40":lambda r:r["rank_turnover"]<=40,
 "change60":lambda r:r["rank_change"]<=60,
 "change100":lambda r:r["rank_change"]<=100,
 "union_turnover20_change60":lambda r:r["rank_turnover"]<=20 or r["rank_change"]<=60,
 "union_turnover40_change60":lambda r:r["rank_turnover"]<=40 or r["rank_change"]<=60,
 "union_turnover20_change100":lambda r:r["rank_turnover"]<=20 or r["rank_change"]<=100,
 "intersection_turnover40_change100":lambda r:r["rank_turnover"]<=40 and r["rank_change"]<=100,
 }
 out={}
 for name,rule in rules.items():
  hits=[o for r,o in cohort if rule(r)]
  n30=sum(o[30] for o in hits);n50=sum(o[50] for o in hits)
  out[name]={"alerts":len(hits),"later30":n30,"later50":n50,
   "nonwinner30":len(hits)-n30,
   "precision30_pct":round(100*n30/len(hits),3) if hits else None}
 return {"status":"SHADOW_FIXED_RULES_IN_SAMPLE","cohort":len(cohort),
   "winner30_total":sum(o[30] for r,o in cohort),"winner50_total":sum(o[50] for r,o in cohort),
   "rules":out,
   "caveat":"Exploratory comparison on same 3 sessions; rules fixed before this run but inspired by same cohort. Not out-of-sample, no fills or BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(compare(p.parse_args().db),sort_keys=True))
