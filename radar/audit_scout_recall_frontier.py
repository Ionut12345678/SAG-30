"""Counterfactual SCOUT first-snapshot candidate rules with full denominators.

Rules are research hypotheses selected after viewing cohort; in-sample only.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 groups=defaultdict(list)
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,
 selected,rank_change,rank_acceleration,rank_impulse,rank_turnover
 FROM scout_history ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups[(r["session"],r["symbol"])].append(r)
 cohorts=defaultdict(list)
 for (session,symbol),rows in groups.items():
  i=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if i is None:continue
  first=rows[i]
  future=[r for r in rows[i+1:] if r["retrieval_ts"]>first["retrieval_ts"]]
  if not future:continue
  cohorts[session].append((first,symbol,any(r["change_pct"]>=30 for r in future),
                           any(r["change_pct"]>=50 for r in future)))
 rules={
  "baseline":lambda r:bool(r["selected"]),
  "change100":lambda r:r["rank_change"]<=100,
  "change100_or_accel20":lambda r:r["rank_change"]<=100 or r["rank_acceleration"]<=20,
  "change100_or_turnover20":lambda r:r["rank_change"]<=100 or r["rank_turnover"]<=20,
  "change100_and_turnover40":lambda r:r["rank_change"]<=100 and r["rank_turnover"]<=40,
  "change60_or_turnover40":lambda r:r["rank_change"]<=60 or r["rank_turnover"]<=40,
 }
 result={}
 for session,cohort in sorted(cohorts.items()):
  result[session]={}
  for name,rule in rules.items():
   chosen=[(s,w30,w50) for r,s,w30,w50 in cohort if rule(r)]
   result[session][name]={"alerts":len(chosen),"later30":sum(w30 for s,w30,w50 in chosen),
                          "later50":sum(w50 for s,w30,w50 in chosen),
                          "nonwinner30":sum(not w30 for s,w30,w50 in chosen)}
 return {"status":"SHADOW_RECALL_FRONTIER_NOT_BUY","by_session":result,
  "caveat":"Rules were inspired by the SAME sessions: in-sample exploratory only, not forward validation. First observed 0..10% and later same-session +30/+50 relative to previous close. No executable prices, no BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
