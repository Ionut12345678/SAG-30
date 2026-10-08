"""Session-level SHADOW comparison of fixed priority rule vs baseline.

Rules are frozen in code. Evaluates first 0..10% observation only; no BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def evaluate(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 groups=defaultdict(list)
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,
 selected,rank_change,rank_turnover FROM scout_history
 ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups[(r["session"],r["symbol"])].append(r)
 sessions=defaultdict(list)
 for (session,symbol),rows in groups.items():
  first=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if first is None:continue
  r=rows[first]
  future=[x for x in rows[first+1:] if x["retrieval_ts"]>r["retrieval_ts"]]
  if not future:continue
  sessions[session].append((r,any(x["change_pct"]>=30 for x in future),
                             any(x["change_pct"]>=50 for x in future)))
 output={}
 for session,cohort in sorted(sessions.items()):
  rules={
   "baseline":lambda r:bool(r["selected"]),
   "priority_turnover40_and_change100":lambda r:r["rank_turnover"]<=40 and r["rank_change"]<=100,
   "turnover20":lambda r:r["rank_turnover"]<=20,
   "change100":lambda r:r["rank_change"]<=100,
  }
  stats={}
  for name,pred in rules.items():
   selected=[(r,w30,w50) for r,w30,w50 in cohort if pred(r)]
   stats[name]={"alerts":len(selected),"later30":sum(w30 for r,w30,w50 in selected),
                "later50":sum(w50 for r,w30,w50 in selected),
                "nonwinner30":sum(not w30 for r,w30,w50 in selected)}
  output[session]={"cohort":len(cohort),"observed_later30":sum(w30 for r,w30,w50 in cohort),
                   "observed_later50":sum(w50 for r,w30,w50 in cohort),"rules":stats}
 return {"status":"SHADOW_PER_SESSION_IN_SAMPLE","sessions":output,
 "note":"Session-level stability diagnostic, not prospective out-of-sample validation. First observed 0..10% per symbol-session, later observed thresholds vs previous close; no fills or BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(evaluate(p.parse_args().db),sort_keys=True))
