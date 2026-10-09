"""SAG-30 v0.4 delayed deep-fetch PAPER audit.

Discovery precedes quote. Entry clock starts ONLY at the first later deep
observation, never at earlier scout time. No backdated quote or paper fill.
"""
import argparse,json,sqlite3
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from radar.early_paper_entry_v02 import evaluate as screen
from radar.paper_outcome_v03 import evaluate as outcome

ET=ZoneInfo("America/New_York")
VERSION="SAG30_DELAYED_ENTRY_AUDIT_V0_4"
def stamp(s):
 try:
  d=datetime.fromisoformat(s.replace("Z","+00:00"))
  return d if d.tzinfo else None
 except (TypeError,ValueError,AttributeError):return None
def audit(path,max_delay_seconds=900,max_examples=40):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 first={}
 for r in db.execute("""SELECT session,symbol,retrieval_ts,change_pct,rank_change,rank_turnover
 FROM scout_history WHERE change_pct>=0 AND change_pct<10
 ORDER BY session,symbol,retrieval_ts,run_id"""):
  first.setdefault((r["session"],r["symbol"]),r)
 by_symbol=defaultdict(list)
 for r in db.execute("SELECT symbol,retrieval_ts,quality,payload,price,change_pct FROM observations ORDER BY symbol,retrieval_ts"):
  by_symbol[r["symbol"]].append(r)
 counts=Counter();blockers=Counter();examples=[];by_session=defaultdict(Counter)
 for (session,symbol),r in first.items():
  counts["eligible"]+=1
  if r["rank_change"]>100:continue
  counts["discovered"]+=1
  priority=r["rank_turnover"]<=40
  if priority:counts["priority"]+=1
  t0=stamp(r["retrieval_ts"])
  if not t0:
   counts["invalid_discovery_timestamp"]+=1;continue
  # First deep fetch AFTER discovery, within TTL. It becomes the entry signal;
  # do not select a later quote just because it passes a screen.
  later=[]
  for o in by_symbol[symbol]:
   t=stamp(o["retrieval_ts"])
   if not t:continue
   delta=(t-t0).total_seconds()
   if 0<=delta<=max_delay_seconds and t.astimezone(ET).date()==t0.astimezone(ET).date():
    later.append(o)
  if not later:
   counts["no_deep_fetch_within_ttl"]+=1;by_session[session]["no_deep_fetch"]+=1
   continue
  o=later[0];counts["deep_fetch_within_ttl"]+=1
  delay=(stamp(o["retrieval_ts"])-t0).total_seconds()
  if delay<=60:counts["delay_le_60s"]+=1
  if delay<=300:counts["delay_le_300s"]+=1
  try:
   snap=json.loads(o["payload"])
   if not isinstance(snap,dict):snap={}
  except (TypeError,ValueError):snap={}
  result=screen(snap,o["retrieval_ts"],o["quality"],o["change_pct"],True,priority,r["retrieval_ts"])
  if not result["paper_review"]:
   counts["quote_screen_blocked"]+=1;blockers.update(result["blockers"])
   if len(examples)<max_examples:examples.append({"session":session,"symbol":symbol,"delay_seconds":delay,"stage":result["stage"],"blockers":result["blockers"]})
   continue
  counts["paper_review"]+=1;by_session[session]["paper_review"]+=1
  entry_ts=o["retrieval_ts"]
  future=[{"ts":f["retrieval_ts"],"price":f["price"]} for f in by_symbol[symbol]
          if stamp(f["retrieval_ts"]) and stamp(f["retrieval_ts"])>stamp(entry_ts)
          and stamp(f["retrieval_ts"]).astimezone(ET).date()==stamp(entry_ts).astimezone(ET).date()]
  perf=outcome(result["indicative_ask"],entry_ts,future)
  if perf["status"]=="INDICATIVE_OUTCOME_NOT_FILL":
   counts["outcome_observed"]+=1
   if perf["net_last_after_assumed_cost_pct"]>0:counts["positive_indicative_net_last"]+=1
  else:counts["outcome_censored"]+=1
  if len(examples)<max_examples:examples.append({"session":session,"symbol":symbol,"delay_seconds":delay,"stage":result["stage"],"indicative_ask":result["indicative_ask"],"outcome":perf})
 return {"version":VERSION,"status":"DELAYED_QUOTE_PAPER_AUDIT_NOT_BUY","counts":dict(counts),
 "blockers_nonexclusive":dict(blockers),"by_session":{k:dict(v) for k,v in sorted(by_session.items())},
 "examples":examples,"max_delay_seconds":max_delay_seconds,
 "method":"First early discovery then first deep observation at/after discovery within 15m; entry clock is later deep observation timestamp. No retroactive entry.",
 "caveat":"Observed later prints and hindsight high are not executable exits; indicative ask not proven fill; no halt/NBBO/cost validation."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 a=p.parse_args();print(json.dumps(audit(a.db),sort_keys=True))
