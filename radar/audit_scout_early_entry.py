"""Measure whether observed pre-threshold SCOUT selections were still under +10%.

This is a timestamped routing study, NOT executable trade performance.
"""
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path
from datetime import datetime

def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 groups={}
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,selected
 FROM scout_history ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups.setdefault((r["session"],r["symbol"]),[]).append(r)
 counts=Counter(); misses=[]
 for (session,symbol),rows in groups.items():
  idx=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if idx is None:continue
  first=rows[idx]
  later=[r for r in rows[idx+1:] if r["retrieval_ts"]>first["retrieval_ts"]]
  if not later:continue
  for threshold in (30,50):
   hit=next((r for r in later if r["change_pct"]>=threshold),None)
   if hit is None:continue
   t=str(threshold);counts["winner_"+t]+=1
   before=[r for r in rows[idx:] if r["retrieval_ts"]<hit["retrieval_ts"]]
   selected=next((r for r in before if r["selected"]),None)
   if selected is None:
    counts["not_selected_before_"+t]+=1
    misses.append({"session":session,"symbol":symbol,"threshold":threshold,
                   "first_under10_ts":first["retrieval_ts"],"first_hit_ts":hit["retrieval_ts"],
                   "reason":"NO_SCOUT_SELECTION_BEFORE_HIT"})
    continue
   counts["selected_before_"+t]+=1
   if 0<=selected["change_pct"]<10:
    counts["selected_while_under10_"+t]+=1
   else:
    counts["selected_after_10_"+t]+=1
   lead=(datetime.fromisoformat(hit["retrieval_ts"])-datetime.fromisoformat(selected["retrieval_ts"])).total_seconds()/60
   for minimum in (5,15,30):
    if lead>=minimum:counts[f"lead_at_least_{minimum}m_"+t]+=1
   if not 0<=selected["change_pct"]<10:
    misses.append({"session":session,"symbol":symbol,"threshold":threshold,
                   "first_under10_ts":first["retrieval_ts"],"first_hit_ts":hit["retrieval_ts"],
                   "first_selection_ts":selected["retrieval_ts"],"first_selection_change_pct":selected["change_pct"],
                   "reason":"FIRST_SELECTION_NOT_UNDER10"})
 return {"status":"SHADOW_EARLY_SELECTION_ONLY","counts":dict(counts),
         "late_or_missing_cases":misses[:50],
         "caveat":"Observed change vs prior close, not entry profit; lead time is snapshot-to-snapshot, not executable. Three-session exploratory cohort; no BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
