"""Capacity-neutral early discovery routing challenger (historical SHADOW).

Per run reserve N deep shortlist positions for first-time early rank-change
leaders that the existing production route did not select. Replace last-ranked
selected symbols, never alter live routing. Counts are coverage counterfactuals,
not proof of valid quotes, fills, or +30/+50 outcomes.
"""
import argparse,json,sqlite3
from collections import Counter,defaultdict
from pathlib import Path

VERSION="SAG30_RESERVED_EARLY_SLOTS_V0_7"
def audit(path,slots=(5,10,20)):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 by_run=defaultdict(list)
 for r in db.execute("""SELECT session,run_id,symbol,retrieval_ts,change_pct,
 rank_change,rank_turnover,selected FROM scout_history
 ORDER BY session,run_id,rank_change,symbol"""):
  by_run[(r["session"],r["run_id"])].append(r)
 first_seen=set()
 metrics={str(k):Counter() for k in slots}
 examples=[]
 for (session,run_id),rows in sorted(by_run.items()):
  eligible=[]
  for r in rows:
   key=(session,r["symbol"])
   if not 0<=r["change_pct"]<10:continue
   if key in first_seen:continue
   first_seen.add(key)
   if r["rank_change"]<=100:eligible.append(r)
  if not eligible:continue
  selected=[r for r in rows if r["selected"]]
  already={r["symbol"] for r in selected}
  missing=[r for r in eligible if r["symbol"] not in already]
  missing.sort(key=lambda r:(r["rank_change"],r["rank_turnover"],r["symbol"]))
  # No production route changes; a hypothetical slot consumes one current slot.
  for k in slots:
   m=metrics[str(k)]
   m["runs_with_early_candidates"]+=1
   m["first_early_discovery"]+=len(eligible)
   m["baseline_selected_early"]+=sum(r["symbol"] in already for r in eligible)
   added=min(k,len(missing),len(selected))
   m["hypothetical_extra_early_coverage"]+=added
   m["hypothetical_displaced_existing_selections"]+=added
   m["still_unselected_early"]+=len(missing)-added
  if len(examples)<30 and missing:
   examples.append({"session":session,"run_id":run_id,
    "first_early_discovery":len(eligible),"baseline_selected":sum(r["symbol"] in already for r in eligible),
    "missing_early":len(missing),"top_missing":[r["symbol"] for r in missing[:5]]})
 return {"version":VERSION,"status":"HISTORICAL_ROUTING_COUNTERFACTUAL_NOT_BUY",
  "by_reserved_slots":{k:dict(v) for k,v in metrics.items()},"examples":examples,
  "caveat":"Hypothetical capacity-neutral swap. Does not simulate lost winner recall of displaced names or actual new deep fetches. Needs separate replay on winners AND false positives and prospective shadow A/B before any production routing change."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 a=p.parse_args();print(json.dumps(audit(a.db),sort_keys=True))
