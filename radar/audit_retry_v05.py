"""SAG-30 v0.5: deterministic retry schedule audit for early PAPER.

Research-only historical replay. After initial deep observation, retry at
+60s and +300s from first quote, selecting the FIRST observed quote at/after
each scheduled time within a 15-minute discovery TTL. No quote cherry-picking.
Observational sampling may miss intended retry times; this is not a live scan.
"""
import argparse,json,sqlite3
from collections import Counter,defaultdict
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from radar.audit_delayed_entry_v04 import stamp
from radar.early_paper_entry_v02 import evaluate as screen
from radar.paper_outcome_v03 import evaluate as outcome

ET=ZoneInfo("America/New_York")
VERSION="SAG30_DETERMINISTIC_RETRY_V0_5"
RETRY_OFFSETS_SECONDS=(0,60,300)
TTL_SECONDS=900

def audit(path,max_cases=200):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 first={}
 for r in db.execute("""SELECT session,symbol,retrieval_ts,change_pct,rank_change,rank_turnover
 FROM scout_history WHERE change_pct>=0 AND change_pct<10
 ORDER BY session,symbol,retrieval_ts,run_id"""):
  first.setdefault((r["session"],r["symbol"]),r)
 deep=defaultdict(list)
 for o in db.execute("SELECT symbol,retrieval_ts,quality,payload,price,change_pct FROM observations ORDER BY symbol,retrieval_ts"):
  t=stamp(o["retrieval_ts"])
  if t:deep[o["symbol"]].append((t,o))
 counts=Counter();blockers=Counter();cases=[];by_session=defaultdict(Counter)
 for (session,symbol),r in first.items():
  if r["rank_change"]>100:continue
  counts["discovery"]+=1
  priority=r["rank_turnover"]<=40
  if priority:counts["priority"]+=1
  t0=stamp(r["retrieval_ts"])
  if not t0:
   counts["invalid_discovery_time"]+=1;continue
  obs=[(t,o) for t,o in deep[symbol] if t>=t0 and (t-t0).total_seconds()<=TTL_SECONDS and t.astimezone(ET).date()==t0.astimezone(ET).date()]
  if not obs:
   counts["no_deep_within_ttl"]+=1;continue
  counts["first_deep_available"]+=1
  first_quote_ts=obs[0][0]
  checked=set();selected=None;attempts=[]
  for offset in RETRY_OFFSETS_SECONDS:
   due=first_quote_ts+timedelta(seconds=offset)
   if (due-t0).total_seconds()>TTL_SECONDS:break
   choice=next(((t,o) for t,o in obs if t>=due and o["retrieval_ts"] not in checked),None)
   if choice is None:
    counts["scheduled_retry_without_observation"]+=1
    continue
   t,o=choice;checked.add(o["retrieval_ts"])
   counts["quote_checks"]+=1
   try:
    payload=json.loads(o["payload"])
    if not isinstance(payload,dict):payload={}
   except (TypeError,ValueError):payload={}
   res=screen(payload,o["retrieval_ts"],o["quality"],o["change_pct"],True,priority,r["retrieval_ts"])
   attempts.append({"offset_due_seconds":offset,"actual_delay_seconds":round((t-t0).total_seconds(),1),
                    "retrieval_ts":o["retrieval_ts"],"pass":res["paper_review"],"blockers":res["blockers"]})
   if res["paper_review"]:
    selected=(t,o,res,offset)
    break
   blockers.update(res["blockers"])
  if not selected:
   counts["not_paper_ready"]+=1
   continue
  t,o,res,offset=selected
  counts["paper_ready"]+=1
  by_session[session]["paper_ready"]+=1
  if offset==0:counts["first_quote_pass"]+=1
  else:counts["retry_rescued"]+=1
  future=[{"ts":f["retrieval_ts"],"price":f["price"]} for ft,f in deep[symbol]
          if ft>t and ft.astimezone(ET).date()==t.astimezone(ET).date()]
  perf=outcome(res["indicative_ask"],o["retrieval_ts"],future)
  if perf["status"]=="INDICATIVE_OUTCOME_NOT_FILL":
   counts["outcome_observed"]+=1
   if perf["net_last_after_assumed_cost_pct"]>0:counts["indicative_last_net_positive"]+=1
   if perf["net_max_after_assumed_cost_pct"]>=30:counts["indicative_hindsight_max_net_30"]+=1
  else:counts["outcome_censored"]+=1
  cases.append({"session":session,"symbol":symbol,"priority":priority,
   "first_discovery_ts":r["retrieval_ts"],"first_discovery_pct":r["change_pct"],
   "paper_entry_ts":o["retrieval_ts"],"entry_change_pct":o["change_pct"],
   "entry_ask":res["indicative_ask"],"retry_offset_seconds":offset,
   "actual_discovery_to_entry_seconds":round((t-t0).total_seconds(),1),
   "attempts":attempts,"outcome":perf})
 return {"version":VERSION,"status":"RESEARCH_RETRY_REPLAY_NOT_BUY",
  "counts":dict(counts),"blockers_nonexclusive":dict(blockers),
  "by_session":{k:dict(v) for k,v in sorted(by_session.items())},
  "paper_cases":cases[:max_cases],"paper_cases_total":len(cases),
  "retry_offsets_from_first_deep_seconds":list(RETRY_OFFSETS_SECONDS),
  "caveat":"Retry schedule replayed over available historical deep snapshots; NOT evidence those polls were made on schedule. First available quote after each due time only, never backdated. Indicative ask/last prints do not prove executable entry/exit. No NBBO, halts or independent edge."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 a=p.parse_args();print(json.dumps(audit(a.db),sort_keys=True))
