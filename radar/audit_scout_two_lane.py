"""Evaluate fixed, transparent two-lane routing at first eligible SCOUT snapshot.

Wide lane = discovery only. Priority lane = review queue, never BUY.
One symbol-session = one record, strictly later outcomes, no hindsight selection.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 groups=defaultdict(list)
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,
 selected,rank_change,rank_turnover FROM scout_history
 ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups[(r["session"],r["symbol"])].append(r)
 sessions=defaultdict(list)
 for (session,symbol),rows in groups.items():
  i=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if i is None:continue
  r=rows[i]
  future=[x for x in rows[i+1:] if x["retrieval_ts"]>r["retrieval_ts"]]
  if not future:continue
  wide=r["rank_change"]<=100
  priority=wide and r["rank_turnover"]<=40
  sessions[session].append({"symbol":symbol,"wide":wide,"priority":priority,
   "baseline":bool(r["selected"]),
   "later30":any(x["change_pct"]>=30 for x in future),
   "later50":any(x["change_pct"]>=50 for x in future)})
 output={}
 for session,cohort in sorted(sessions.items()):
  stats={}
  for lane in ("baseline","wide","priority"):
   chosen=[x for x in cohort if x[lane]]
   stats[lane]={"candidates":len(chosen),"later30":sum(x["later30"] for x in chosen),
    "later50":sum(x["later50"] for x in chosen),
    "nonwinner30":sum(not x["later30"] for x in chosen)}
  stats["wide_not_priority"]={"candidates":sum(x["wide"] and not x["priority"] for x in cohort),
   "later30":sum(x["wide"] and not x["priority"] and x["later30"] for x in cohort),
   "later50":sum(x["wide"] and not x["priority"] and x["later50"] for x in cohort)}
  output[session]=stats
 return {"status":"SHADOW_TWO_LANE_FIRST_SNAPSHOT_NOT_BUY",
 "sessions":output,"priority_is_subset_of_wide":True,
 "caveat":"Wide lane is NOT alertable BUY; priority lane is NOT executable. In-sample same three sessions, prior-close thresholds, no spreads/halts/slippage or independent validation."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
