"""Read-only report of actual additive early-paper snapshot fetches.
Only observed quotes; no inferred fills, no orders.
"""
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path
def build(path,limit=40):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='early_paper_extra_observations'").fetchone()
 if not exists:return {"version":"SAG30_EXTRA_QUOTES_V11","status":"NO_OBSERVATIONS_YET","total":0,"paper_review":0,"cases":[]}
 rows=db.execute("""SELECT run_id,session,symbol,discovery_ts,discovery_pct,quote_retrieved_ts,
 trade_ts,quote_ts,bid,ask,trade_price,spread_pct,screen_stage,blockers_json,feed
 FROM early_paper_extra_observations ORDER BY run_id DESC,symbol""").fetchall()
 count=Counter(r["screen_stage"] for r in rows)
 cases=[]
 for r in rows[:limit]:
  x=dict(r)
  try:x["blockers"]=json.loads(x.pop("blockers_json"))
  except (TypeError,ValueError):x["blockers"]=[];x.pop("blockers_json",None)
  cases.append(x)
 return {"version":"SAG30_EXTRA_QUOTES_V11","status":"REAL_SNAPSHOT_SHADOW_NOT_BUY",
  "total":len(rows),"paper_review":count["EARLY_PAPER_ENTRY_REVIEW"],
  "stages":dict(count),"latest_run":max((r["run_id"] for r in rows),default=None),
  "cases":cases,"caveat":"IEX snapshot, not NBBO; quote screen is PAPER only, not an executable fill or validated edge."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--out",required=True)
 a=p.parse_args();Path(a.out).write_text(json.dumps(build(a.db),indent=2))
