"""Audit early PAPER entry v0.2 against actual SQLite SCOUT + observations.

No future joins: only a deep observation with retrieval_ts <= SCOUT timestamp
and <= 60s old can supply a quote. Missing coverage is a separate category.
Research-only: no orders, no claimed fills or profit.
"""
import argparse,json,sqlite3
from collections import Counter,defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
from pathlib import Path
from radar.early_paper_entry_v02 import evaluate as screen
from radar.paper_outcome_v03 import evaluate as outcome

VERSION="SAG30_REAL_PAPER_AUDIT_V0_3"
def _dt(ts):
 try:
  d=datetime.fromisoformat(ts.replace("Z","+00:00"))
  return d if d.tzinfo is not None else None
 except (ValueError,TypeError,AttributeError):return None
def audit(path,session_start=None,max_examples=30):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 q="""SELECT session,symbol,retrieval_ts,run_id,change_pct,rank_change,rank_turnover
      FROM scout_history WHERE change_pct>=0 AND change_pct<10"""
 params=[]
 if session_start:
  q+=" AND session>=?";params.append(session_start)
 q+=" ORDER BY session,symbol,retrieval_ts,run_id"
 rows=db.execute(q,params).fetchall()
 grouped=defaultdict(list)
 for r in rows:grouped[(r["session"],r["symbol"])].append(r)
 counts=Counter();blockers=Counter();examples=[]
 by_session=defaultdict(Counter)
 # Same run+symbol observations are eligible only if captured before scout timestamp.
 # Avoid joining by symbol alone: that could import later data into an earlier decision.
 obs_by_key=defaultdict(list)
 for o in db.execute("SELECT run_id,symbol,retrieval_ts,quality,payload,price FROM observations ORDER BY retrieval_ts"):
  obs_by_key[(o["run_id"],o["symbol"])].append(o)
 future_by_key=defaultdict(list)
 for o in db.execute("SELECT symbol,retrieval_ts,price FROM observations WHERE price>0 ORDER BY symbol,retrieval_ts"):
  future_by_key[o["symbol"]].append(o)
 for (session,symbol),scouts in grouped.items():
  counts["eligible_symbol_sessions"]+=1;by_session[session]["eligible"]+=1
  first=scouts[0]
  discovered=first["rank_change"]<=100
  priority=discovered and first["rank_turnover"]<=40
  if not discovered:
   counts["not_discovered_at_first_eligible"]+=1
   continue
  counts["discovered_at_first_eligible"]+=1
  if priority:counts["priority_at_first_eligible"]+=1
  scout_ts=_dt(first["retrieval_ts"])
  candidates=obs_by_key.get((first["run_id"],symbol),[])
  eligible=[]
  for o in candidates:
   t=_dt(o["retrieval_ts"])
   if t and scout_ts and 0<=(scout_ts-t).total_seconds()<=60:
    eligible.append(o)
  if not eligible:
   counts["no_contemporaneous_deep_snapshot"]+=1
   by_session[session]["no_snapshot"]+=1
   continue
  o=eligible[-1];counts["matched_deep_snapshot"]+=1
  try:
   payload=json.loads(o["payload"])
   if not isinstance(payload,dict):payload={}
  except (TypeError,ValueError):payload={}
  r=screen(payload,first["retrieval_ts"],o["quality"],first["change_pct"],
           discovered,priority,first["retrieval_ts"])
  if not r["paper_review"]:
   counts["screen_blocked"]+=1
   blockers.update(r["blockers"])
   if len(examples)<max_examples:examples.append({"session":session,"symbol":symbol,"stage":r["stage"],"blockers":r["blockers"]})
   continue
  counts["paper_review"]+=1;by_session[session]["paper_review"]+=1
  ask=r["indicative_ask"]
  forward=[]
  for f in future_by_key[symbol]:
   t=_dt(f["retrieval_ts"])
   if t and scout_ts and t>scout_ts and t.astimezone(ET).date()==scout_ts.astimezone(ET).date():
    forward.append({"ts":f["retrieval_ts"],"price":f["price"]})
  result=outcome(ask,first["retrieval_ts"],forward)
  if result["status"]=="INDICATIVE_OUTCOME_NOT_FILL":
   counts["paper_with_later_observation"]+=1
   if result["net_last_after_assumed_cost_pct"]>0:counts["indicative_net_last_positive"]+=1
  else:counts["paper_censored"]+=1
  if len(examples)<max_examples:examples.append({"session":session,"symbol":symbol,
   "stage":r["stage"],"indicative_ask":ask,"outcome":result})
 return {"version":VERSION,"status":"REAL_DATA_RESEARCH_NOT_BUY",
  "counts":dict(counts),"blockers_nonexclusive":dict(blockers),
  "by_session":{k:dict(v) for k,v in sorted(by_session.items())},
  "examples":examples,
  "method":"First 0-<10% SCOUT observation per symbol-session. Match only same-run symbol deep snapshot retrieved at or before SCOUT timestamp and no more than 60s old. Later observations are used only for outcome.",
  "limitations":"If SCOUT precedes deep fetch, it will be marked NO_CONTEMPORANEOUS_DEEP_SNAPSHOT; this is an honest data coverage gap, not a strategy failure. Later prices are trade prints, not exit bids. No real fills, halt validation, consolidated NBBO or proven edge."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--session-start")
 a=p.parse_args();print(json.dumps(audit(a.db,a.session_start),sort_keys=True))
