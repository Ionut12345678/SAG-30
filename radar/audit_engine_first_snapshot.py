"""Audit actual multi-engine routing at first eligible SCOUT observation.

Join is on (run_id, symbol) only. Outcomes are strictly later SCOUT
observations in the same session. Descriptive SHADOW, never BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 engines={(r["run_id"],r["symbol"]):r for r in db.execute(
  "SELECT run_id,symbol,base_selected,dual_selected,high_recall FROM multi_engine_scores")}
 groups=defaultdict(list)
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,
 selected,rank_turnover,rank_change FROM scout_history
 ORDER BY session,symbol,retrieval_ts,run_id"""):
  groups[(r["session"],r["symbol"])].append(r)
 cohort=[]
 for rows in groups.values():
  i=next((i for i,r in enumerate(rows) if 0<=r["change_pct"]<10),None)
  if i is None:continue
  first=rows[i]
  future=[r for r in rows[i+1:] if r["retrieval_ts"]>first["retrieval_ts"]]
  if not future:continue
  outcome={t:any(r["change_pct"]>=t for r in future) for t in (30,50)}
  cohort.append((first,engines.get((first["run_id"],first["symbol"])),outcome))
 rules={
  "scout_selected":lambda r,e:bool(r["selected"]),
  "shadow_priority":lambda r,e:r["rank_turnover"]<=40 and r["rank_change"]<=100,
  "engine_base_selected":lambda r,e:e is not None and bool(e["base_selected"]),
  "engine_dual_selected":lambda r,e:e is not None and bool(e["dual_selected"]),
  "engine_high_recall":lambda r,e:e is not None and bool(e["high_recall"]),
 }
 stats={}
 for name,rule in rules.items():
  chosen=[o for r,e,o in cohort if rule(r,e)]
  stats[name]={"alerts":len(chosen),"later30":sum(o[30] for o in chosen),
               "later50":sum(o[50] for o in chosen),
               "nonwinner30":sum(not o[30] for o in chosen)}
 missing=[(r,o) for r,e,o in cohort if e is None]
 return {"status":"SHADOW_ENGINE_FIRST_SNAPSHOT_AUDIT_NOT_BUY",
  "cohort":len(cohort),"engine_joined":len(cohort)-len(missing),
  "engine_missing":len(missing),
  "engine_missing_later30":sum(o[30] for r,o in missing),
  "engine_missing_later50":sum(o[50] for r,o in missing),
  "total_later30":sum(o[30] for r,e,o in cohort),
  "total_later50":sum(o[50] for r,e,o in cohort),
  "rules":stats,
  "caveat":"Same-session first observed 0..10% snapshot; later thresholds relative to prior close, not trade returns. Missing multi-engine joins are not negative signals. Three-session in-sample audit; no BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
