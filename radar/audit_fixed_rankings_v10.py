"""SAG30 v1.0: predeclared additive ranking benchmark by session.

No optimization using future labels. Compare three fixed rankings for 3
additional deep quotes per run: change rank, turnover rank, and balanced.
Censored outcomes reported separately. No live fetch, no BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict,Counter
from pathlib import Path
METHODS=("change","turnover","balanced")
def audit(path,budget=3):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 runs=defaultdict(list);history=defaultdict(list)
 for r in db.execute("SELECT session,run_id,symbol,retrieval_ts,change_pct,rank_change,rank_turnover,selected FROM scout_history ORDER BY session,run_id,rank_change,symbol"):
  runs[(r["session"],r["run_id"])].append(r);history[(r["session"],r["symbol"])].append(r)
 seen=set();by_day=defaultdict(lambda:{m:Counter() for m in METHODS})
 for (session,run_id),rows in sorted(runs.items()):
  available=[]
  for r in rows:
   key=(session,r["symbol"])
   if r["change_pct"] is None or not 0<=r["change_pct"]<10 or key in seen:continue
   seen.add(key)
   if r["rank_change"] is not None and r["rank_change"]<=100 and not r["selected"]:available.append(r)
  for method in METHODS:
   def score(r):
    a=r["rank_change"] if r["rank_change"] is not None else 999999
    b=r["rank_turnover"] if r["rank_turnover"] is not None else 999999
    if method=="change":return (a,b,r["symbol"])
    if method=="turnover":return (b,a,r["symbol"])
    return (a+b,a,b,r["symbol"])
   selected=sorted(available,key=score)[:budget]
   c=by_day[session][method]
   c["selected"]+=len(selected)
   for r in selected:
    later=[x["change_pct"] for x in history[(session,r["symbol"])] if x["retrieval_ts"]>r["retrieval_ts"] and x["change_pct"] is not None]
    if not later:c["censored"]+=1
    else:
     c["labeled"]+=1;c["later30"]+=int(any(x>=30 for x in later));c["later50"]+=int(any(x>=50 for x in later))
 output={}
 for method in METHODS:
  agg=Counter()
  for day in by_day:agg.update(by_day[day][method])
  output[method]={**dict(agg),"observed_later30_precision_pct":round(100*agg["later30"]/agg["labeled"],2) if agg["labeled"] else None}
 return {"version":"SAG30_FIXED_RANKINGS_V1_0","status":"HISTORICAL_SHADOW_NOT_BUY",
 "budget_per_run":budget,"total":output,"by_session":{d:{m:dict(c) for m,c in x.items()} for d,x in sorted(by_day.items())},
 "caveat":"Fixed rules, but still same 3 historical sessions. Only first eligible symbol-session and strictly later SCOUT prices. Labels relative previous close, not buy returns; no actual quote fetch, fill, or independent validation."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
