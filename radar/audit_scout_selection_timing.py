"""Audit whether SCOUT selected observed future winners before +30/+50.

Observed change vs previous close only; not executable fills or BUY.
"""
import argparse,json,sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 rows=db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,selected,
 rank_change,rank_acceleration FROM scout_history
 ORDER BY session,symbol,retrieval_ts,run_id""")
 groups={}
 for row in rows:
  groups.setdefault((row["session"],row["symbol"]),[]).append(row)
 totals=Counter(); examples=[]
 for (session,symbol),series in groups.items():
  first=next((i for i,r in enumerate(series) if 0<=r["change_pct"]<10),None)
  if first is None: continue
  start=series[first]
  future=[r for r in series[first+1:] if r["retrieval_ts"]>start["retrieval_ts"]]
  if not future: continue
  totals["eligible_followed"]+=1
  for threshold in (30,50):
   hit=next((r for r in future if r["change_pct"]>=threshold),None)
   if hit is None: continue
   label=str(threshold)
   totals["winner_"+label]+=1
   # Baseline must be selected strictly before the first observed threshold hit.
   before=[r for r in series[first:] if r["retrieval_ts"]<hit["retrieval_ts"]]
   selected=next((r for r in before if r["selected"]),None)
   if selected:
    totals["selected_before_"+label]+=1
    if selected["retrieval_ts"]==start["retrieval_ts"]:
     totals["selected_at_first_under10_"+label]+=1
    else:
     totals["selected_later_before_"+label]+=1
   else:
    totals["missed_before_"+label]+=1
   if len(examples)<50:
    examples.append({"session":session,"symbol":symbol,"threshold":threshold,
      "first_under10_ts":start["retrieval_ts"],"first_threshold_ts":hit["retrieval_ts"],
      "selected_before":bool(selected),
      "first_selected_ts":selected["retrieval_ts"] if selected else None})
 return {"status":"SHADOW_TIMING_AUDIT_NOT_BUY","counts":dict(totals),
         "examples":examples,"caveat":"Observed threshold relative to previous close, not realized entry returns. Sparse observations, quote spread, halts and selection feasibility not assessed."}

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
