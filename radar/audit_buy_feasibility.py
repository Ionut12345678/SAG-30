"""Conservative first-snapshot BUY feasibility audit on already collected data.

Does not infer executable fills from SCOUT last prices. Reports observed
recall, candidate burden, and missing execution evidence separately.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 rows=db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,selected,
 rank_change,rank_turnover FROM scout_history
 ORDER BY session,symbol,retrieval_ts,run_id""").fetchall()
 grouped=defaultdict(list)
 for r in rows:grouped[(r["session"],r["symbol"])].append(r)
 totals=defaultdict(lambda:{"candidates":0,"later30":0,"later50":0,"observed_nonwinner30":0})
 by_session=defaultdict(lambda:defaultdict(lambda:{"candidates":0,"later30":0,"later50":0}))
 cohort=0;later30_total=0;later50_total=0;censored=0
 for (session,symbol),observations in grouped.items():
  first=next((i for i,r in enumerate(observations) if r["change_pct"] is not None and 0<=r["change_pct"]<10),None)
  if first is None:continue
  r=observations[first]
  future=[f for f in observations[first+1:] if f["retrieval_ts"]>r["retrieval_ts"]]
  if not future:
   censored+=1
   continue
  cohort+=1
  hit30=any(f["change_pct"] is not None and f["change_pct"]>=30 for f in future)
  hit50=any(f["change_pct"] is not None and f["change_pct"]>=50 for f in future)
  later30_total+=hit30;later50_total+=hit50
  lanes={"baseline":bool(r["selected"]),
   "discovery":r["rank_change"] is not None and r["rank_change"]<=100,
   "priority":r["rank_change"] is not None and r["rank_change"]<=100 and r["rank_turnover"] is not None and r["rank_turnover"]<=40}
  for lane,chosen in lanes.items():
   if not chosen:continue
   a=totals[lane];b=by_session[session][lane]
   a["candidates"]+=1;a["later30"]+=hit30;a["later50"]+=hit50;a["observed_nonwinner30"]+=not hit30
   b["candidates"]+=1;b["later30"]+=hit30;b["later50"]+=hit50
 for lane,a in totals.items():
  a["observed_precision30_pct"]=round(100*a["later30"]/a["candidates"],2) if a["candidates"] else None
  a["observed_recall30_pct"]=round(100*a["later30"]/later30_total,2) if later30_total else None
  a["observed_recall50_pct"]=round(100*a["later50"]/later50_total,2) if later50_total else None
  a["not_a_trading_win_rate"]=True
 return {"status":"BUY_FEASIBILITY_RESEARCH_ONLY_NOT_APPROVED",
 "cohort_with_future":cohort,"no_future_observation_excluded":censored,
 "later30_total":later30_total,"later50_total":later50_total,
 "lanes":dict(totals),"by_session":{k:dict(v) for k,v in sorted(by_session.items())},
 "buy_gate":{"approved":False,"reason":"No matched time-of-signal executable NBBO/ask, halt status, fees, slippage and forward independent sessions. Observed future +30/+50 vs previous close is not net return from entry."},
 "research_decision":"Keep DISCOVERY broad, PRIORITY as review queue; do not issue BUY on historical threshold conversion alone."}

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
