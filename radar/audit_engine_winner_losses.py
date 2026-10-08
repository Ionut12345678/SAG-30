"""Inspect actual first-snapshot winners lost by multi-engine lanes.

Read-only descriptive diagnostic. No thresholds are changed, no BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 engines={(r["run_id"],r["symbol"]):r for r in db.execute(
  "SELECT * FROM multi_engine_scores")}
 groups=defaultdict(list)
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,selected,
 rank_change,rank_acceleration,rank_impulse,rank_turnover FROM scout_history
 ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups[(r["session"],r["symbol"])].append(r)
 winners=[]
 for (session,symbol),rows in groups.items():
  i=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if i is None:continue
  r=rows[i]
  future=[x for x in rows[i+1:] if x["retrieval_ts"]>r["retrieval_ts"]]
  if not future or not any(x["change_pct"]>=30 for x in future):continue
  e=engines.get((r["run_id"],symbol))
  engine=dict(e) if e is not None else None
  winners.append({"session":session,"symbol":symbol,
   "first_change_pct":r["change_pct"],"first_ts":r["retrieval_ts"],
   "scout_selected":bool(r["selected"]),
   "priority":r["rank_turnover"]<=40 and r["rank_change"]<=100,
   "ranks":{k:r[k] for k in ("rank_change","rank_acceleration","rank_impulse","rank_turnover")},
   "engine":engine,
   "later50":any(x["change_pct"]>=50 for x in future)})
 return {"status":"SHADOW_WINNER_ENGINE_DIAGNOSTIC_NOT_BUY",
 "winner_count":len(winners),"winners":winners,
 "caveat":"Outcomes used solely for audit after selection; engine fields are original contemporaneous snapshots. Same three in-sample sessions; no fills, no BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True,default=str))
