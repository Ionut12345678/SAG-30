"""Diagnose why early DISCOVERY candidates lack deep quote snapshots.

Separates NOT_ROUTED, ROUTED_NO_DEEP, DEEP_SAME_RUN and DEEP_LATER.
Historical observational audit, not a live quote fetch or BUY.
"""
import argparse,json,sqlite3
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path

VERSION="SAG30_DEEP_COVERAGE_DIAGNOSTIC_V0_6"
def ts(s):
 try:
  d=datetime.fromisoformat(s.replace("Z","+00:00"))
  return d if d.tzinfo else None
 except (TypeError,ValueError,AttributeError):return None

def audit(path,limit_examples=30):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 first={}
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,
 rank_change,rank_turnover,selected FROM scout_history
 WHERE change_pct>=0 AND change_pct<10 ORDER BY session,symbol,retrieval_ts,run_id"""):
  first.setdefault((r["session"],r["symbol"]),r)
 obs=defaultdict(list)
 for r in db.execute("SELECT run_id,symbol,retrieval_ts,quality FROM observations ORDER BY symbol,retrieval_ts"):
  t=ts(r["retrieval_ts"])
  if t:obs[r["symbol"]].append((t,r))
 counts=Counter();by_session=defaultdict(Counter);examples=[]
 for (session,symbol),r in first.items():
  if r["rank_change"]>100:continue
  counts["discovery"]+=1
  first_t=ts(r["retrieval_ts"])
  if not first_t:counts["invalid_first_timestamp"]+=1;continue
  same=[(t,o) for t,o in obs[symbol] if o["run_id"]==r["run_id"] and t>=first_t]
  next15=[(t,o) for t,o in obs[symbol] if 0<=(t-first_t).total_seconds()<=900]
  if r["selected"]:
   counts["selected_at_first"]+=1
   category="SELECTED_SAME_RUN_DEEP" if same else "SELECTED_NO_SAME_RUN_DEEP"
  else:
   counts["not_selected_at_first"]+=1
   category="NOT_SELECTED_AT_FIRST"
  counts[category]+=1;by_session[session][category]+=1
  if next15:
   counts["any_deep_within_15m"]+=1
   if r["selected"]:counts["selected_within_15m"]+=1
   else:counts["unselected_but_later_deep"]+=1
  else:
   counts["no_deep_within_15m"]+=1
   if not r["selected"]:counts["unselected_no_deep_within_15m"]+=1
  if len(examples)<limit_examples and (not r["selected"] or not next15):
   examples.append({"session":session,"symbol":symbol,"first_pct":r["change_pct"],
    "rank_change":r["rank_change"],"rank_turnover":r["rank_turnover"],
    "selected_at_first":bool(r["selected"]),"same_run_deep":bool(same),
    "deep_within_15m":bool(next15)})
 return {"version":VERSION,"status":"SHADOW_COVERAGE_DIAGNOSTIC_NOT_BUY",
 "counts":dict(counts),"by_session":{k:dict(v) for k,v in sorted(by_session.items())},
 "examples":examples,"interpretation":"selected is the production routing flag at FIRST early SCOUT observation, not proof of a timely quote. Unselected discovery candidates are a routing coverage issue; selected candidates without deep data indicate acquisition/retention gaps. Deep observation does not imply valid trade/quote.",
 "caveat":"Historical 3-session sample; no intervention performed, no execution or edge claim."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 a=p.parse_args();print(json.dumps(audit(a.db),sort_keys=True))
