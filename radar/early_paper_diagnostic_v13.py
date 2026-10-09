"""Descriptive PAPER screen diagnostics, not a BUY model."""
import argparse,json,sqlite3
from collections import Counter
def build(path):
 db=sqlite3.connect(path)
 db.row_factory=sqlite3.Row
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 if "early_paper_extra_observations" not in tables:return {"status":"NO_DATA"}
 rows=list(db.execute("SELECT run_id,session,symbol,discovery_pct,ask,spread_pct,screen_stage,blockers_json FROM early_paper_extra_observations"))
 counts=Counter(r["screen_stage"] for r in rows)
 blockers=Counter()
 entries={}
 for r in rows:
  try:blockers.update(json.loads(r["blockers_json"] or "[]"))
  except (TypeError,ValueError):blockers["INVALID_BLOCKERS"]+=1
  if r["screen_stage"]=="EARLY_PAPER_ENTRY_REVIEW":
   entries.setdefault((r["session"],r["symbol"]),r)
 cases=[]
 for (session,symbol),r in entries.items():
  later=[]
  if "early_paper_follow_v12" in tables:
   later=[x[0] for x in db.execute("SELECT indicative_return_pct FROM early_paper_follow_v12 WHERE entry_run_id=? AND symbol=? AND status='FRESH_LATER_TRADE' AND indicative_return_pct IS NOT NULL ORDER BY follow_run_id",(r["run_id"],symbol))]
  peak=max(later) if later else None
  cases.append({"symbol":symbol,"entry_ask":r["ask"],"discovery_pct":r["discovery_pct"],"entry_spread_pct":r["spread_pct"],"later_trades":len(later),"max_observed_pct":peak,"last_observed_pct":later[-1] if later else None,"observed_10_plus":peak>=10 if peak is not None else None,"observed_30_plus":peak>=30 if peak is not None else None})
 return {"version":"SAG30_PAPER_DIAGNOSTIC_V13","status":"DESCRIPTIVE_SHADOW_NOT_BUY","checked":len(rows),"quote_passes":counts["EARLY_PAPER_ENTRY_REVIEW"],"stages":dict(counts),"blockers":dict(blockers),"cases":cases,"warning":"Quote eligibility is not momentum prediction. Sparse IEX samples; no actual fills, highs, or final outcomes."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--out",required=True);a=p.parse_args()
 with open(a.out,"w") as f:json.dump(build(a.db),f,indent=2)
