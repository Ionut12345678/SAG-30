"""SAG30 v0.9 additive SHADOW quote-budget challenger.

No production selections displaced. Rank first-eligible DISCOVERY candidates
not selected in the current run by rank_turnover then rank_change; evaluate
1/3/5 extra hypothetical quote requests per run. Strict later price labels,
censored explicit. No actual additional API calls or BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict,Counter
from pathlib import Path
def audit(path,budgets=(0,1,3,5)):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 runs=defaultdict(list);symbols=defaultdict(list)
 for r in db.execute("SELECT session,run_id,symbol,retrieval_ts,change_pct,rank_change,rank_turnover,selected FROM scout_history ORDER BY session,run_id,rank_change,symbol"):
  runs[(r["session"],r["run_id"])].append(r);symbols[(r["session"],r["symbol"])].append(r)
 def future(r):
  values=[x["change_pct"] for x in symbols[(r["session"],r["symbol"])] if x["retrieval_ts"]>r["retrieval_ts"] and x["change_pct"] is not None]
  return None if not values else (any(x>=30 for x in values),any(x>=50 for x in values))
 seen=set();totals={k:Counter() for k in budgets};examples=[]
 for (session,run_id),rows in sorted(runs.items()):
  first=[]
  for r in rows:
   key=(session,r["symbol"])
   if r["change_pct"] is None or not 0<=r["change_pct"]<10 or key in seen:continue
   seen.add(key)
   if r["rank_change"] is not None and r["rank_change"]<=100 and not r["selected"]:first.append(r)
  first.sort(key=lambda r:(0 if r["rank_turnover"] is not None and r["rank_turnover"]<=40 else 1,
                           r["rank_turnover"] if r["rank_turnover"] is not None else 10**9,r["rank_change"],r["symbol"]))
  for k,m in totals.items():
   m["runs"]+=1;m["eligible_unselected"]+=len(first)
   chosen=first[:k];m["extra_requests_upper_bound"]+=len(chosen)
   for r in chosen:
    label=future(r)
    if label is None:m["censored"]+=1
    else:
     m["labeled"]+=1;m["later30"]+=int(label[0]);m["later50"]+=int(label[1])
     m["nonwinner30"]+=int(not label[0])
   if k==3 and chosen and len(examples)<20:
    examples.append({"session":session,"run_id":run_id,"candidates":[{"symbol":r["symbol"],"pct":r["change_pct"],"rank_turnover":r["rank_turnover"],"later":future(r)} for r in chosen]})
 result={}
 for k,m in totals.items():
  result[str(k)]={**dict(m),"observed_later30_precision_pct":round(100*m["later30"]/m["labeled"],2) if m["labeled"] else None,
   "censored_fraction_pct":round(100*m["censored"]/m["extra_requests_upper_bound"],2) if m["extra_requests_upper_bound"] else None}
 return {"version":"SAG30_ADDITIVE_SHADOW_V09","status":"HISTORICAL_RESEARCH_NO_EXTRA_FETCHES_YET","variants":result,"examples":examples,
 "limitations":"Counterfactual extra requests only, no actual API usage or quote validity. Labels are later SCOUT threshold vs prior close, not entry returns; selection in-sample, censored cases excluded from precision."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
