"""Prospective shadow comparison of PAPER entries with matched scout controls.

Pre-entry momentum only. Later scout observations are sampled, not intrabar highs.
No orders, no BUY promotion, no threshold optimization.
"""
import argparse,json,sqlite3
from collections import defaultdict
def build(path):
 db=sqlite3.connect(path);db.row_factory=sqlite3.Row
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 if not {"early_paper_extra_observations","scout_history"}.issubset(tables):
  return {"status":"MISSING_INPUT","version":"SAG30_MOMENTUM_SHADOW_V14"}
 entries=list(db.execute("""SELECT e.run_id,e.session,e.symbol,e.discovery_pct,e.ask,e.trade_price
 FROM early_paper_extra_observations e WHERE e.screen_stage='EARLY_PAPER_ENTRY_REVIEW'
 AND e.ask>0 AND e.run_id=(SELECT MIN(x.run_id) FROM early_paper_extra_observations x
 WHERE x.session=e.session AND x.symbol=e.symbol AND x.screen_stage='EARLY_PAPER_ENTRY_REVIEW' AND x.ask>0)
 ORDER BY e.run_id,e.symbol"""))
 def history(symbol,session,run_id):
  return list(db.execute("""SELECT run_id,change_pct,acceleration_pp_per_min,fresh_turnover_impulse_per_min
   FROM scout_history WHERE symbol=? AND session=? AND run_id<=?
   ORDER BY run_id DESC LIMIT 3""",(symbol,session,run_id)))
 def features(rows):
  if len(rows)<3:return {"sufficient_history":False,"positive_accel_streak_3":None,"positive_impulse_streak_3":None}
  return {"sufficient_history":True,
   "positive_accel_streak_3":all(r["acceleration_pp_per_min"]>0 for r in rows),
   "positive_impulse_streak_3":all(r["fresh_turnover_impulse_per_min"]>0 for r in rows),
   "entry_acceleration_pp_per_min":rows[0]["acceleration_pp_per_min"],
   "entry_impulse_per_min":rows[0]["fresh_turnover_impulse_per_min"]}
 cases=[];controls=[]
 for e in entries:
  run,session,symbol=e["run_id"],e["session"],e["symbol"]
  cases.append({"symbol":symbol,"session":session,"entry_run_id":run,"entry_change_pct":e["discovery_pct"],**features(history(symbol,session,run))})
  # Deterministic same-run negative-control candidates, selected without future outcomes.
  matches=list(db.execute("""SELECT symbol,change_pct FROM scout_history
    WHERE run_id=? AND session=? AND symbol<>? AND change_pct>=0 AND change_pct<10
    ORDER BY ABS(change_pct-?),symbol LIMIT 5""",(run,session,symbol,e["discovery_pct"])))
  for m in matches:
   controls.append({"entry_symbol":symbol,"symbol":m["symbol"],"entry_run_id":run,
    "entry_change_pct":m["change_pct"],**features(history(m["symbol"],session,run))})
 def counts(items):
  eligible=[r for r in items if r["sufficient_history"]]
  return {"total":len(items),"with_3_observations":len(eligible),
   "both_positive_3":sum(r["positive_accel_streak_3"] and r["positive_impulse_streak_3"] for r in eligible),
   "accel_positive_3":sum(r["positive_accel_streak_3"] for r in eligible),
   "impulse_positive_3":sum(r["positive_impulse_streak_3"] for r in eligible)}
 return {"version":"SAG30_MOMENTUM_SHADOW_V14","status":"EXPLORATORY_NOT_BUY",
  "pre_registered_definition":"Three most recent scout snapshots at or before the PAPER entry run: strictly positive acceleration and strictly positive incremental turnover impulse in all three.",
  "paper":counts(cases),"matched_controls":counts(controls),
  "paper_cases":cases,"control_cases":controls,
  "caveats":["Controls are same-run nearest discovery-change observations, not known losers; future outcomes are not yet evaluated",
  "A positive three-cycle streak is descriptive, not validated predictive advantage",
  "Scout snapshots may have missing or delayed IEX prints; no NBBO, execution or causal attribution",
  "Do not change frozen BUY or tune thresholds based on this small sample"]}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--out",required=True)
 a=p.parse_args()
 with open(a.out,"w") as f:json.dump(build(a.db),f,indent=2)
