"""Pre-registered SHADOW top-K scout rank replay with full nonwinner denominator.

Ranking uses only observed fields at each snapshot. Evaluation labels are strictly
later same-session SCOUT observations. No trade fills or BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def replay(path, ks=(20,40,60,100)):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 groups=defaultdict(list)
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,
 selected,rank_change,rank_acceleration,rank_impulse,rank_turnover
 FROM scout_history ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups[(r["session"],r["symbol"])].append(r)
 cohorts=[]
 for (session,symbol),rows in groups.items():
  first=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if first is None:continue
  entry=rows[first]
  future=[r for r in rows[first+1:] if r["retrieval_ts"]>entry["retrieval_ts"]]
  if not future:continue
  # First eligible snapshot: no hindsight choice of favorable later rank.
  cohorts.append((entry,{t:any(r["change_pct"]>=t for r in future) for t in (30,50)}))
 result={}
 for family in ("rank_change","rank_acceleration","rank_impulse","rank_turnover"):
  result[family]={}
  for k in ks:
   selected=[(r,o) for r,o in cohorts if r[family]<=k]
   result[family][str(k)]={"alerts":len(selected),
      "winner30":sum(o[30] for r,o in selected),
      "winner50":sum(o[50] for r,o in selected),
      "nonwinner30":sum(not o[30] for r,o in selected),
      "precision30_pct":round(100*sum(o[30] for r,o in selected)/len(selected),3) if selected else None}
 baseline=[(r,o) for r,o in cohorts if r["selected"]]
 return {"status":"SHADOW_FIRST_SNAPSHOT_REPLAY","cohort":len(cohorts),
   "all_winner30":sum(o[30] for r,o in cohorts),
   "all_winner50":sum(o[50] for r,o in cohorts),
   "baseline_first_snapshot":{"alerts":len(baseline),
      "winner30":sum(o[30] for r,o in baseline),
      "winner50":sum(o[50] for r,o in baseline)},
   "rank_top_k":result,
   "caveat":"Single first observed 0..10% snapshot per symbol-session; follow-up required; rankings recorded at snapshot, but cross-run top-K can exceed K per run. No executable quotes/fills. Exploratory in-sample comparison, NOT BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(replay(p.parse_args().db),sort_keys=True))
