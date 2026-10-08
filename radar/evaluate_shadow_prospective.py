"""Read-only forward evaluation of a frozen append-only SHADOW ledger.

No outcome field is ever written into the immutable candidate ledger.
"""
import argparse,json,sqlite3
from collections import defaultdict
from pathlib import Path

def evaluate(db_path,ledger_path):
 db=sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 records=[json.loads(x) for x in Path(ledger_path).read_text().splitlines() if x.strip()]
 seen=set()
 for r in records:
  key=(r["session"],r["symbol"])
  if key in seen:raise ValueError("duplicate candidate "+str(key))
  seen.add(key)
 snapshots=defaultdict(list)
 for r in db.execute("SELECT session,symbol,retrieval_ts,change_pct FROM scout_history ORDER BY retrieval_ts"):
  if (r["session"],r["symbol"]) in seen:snapshots[(r["session"],r["symbol"])].append(r)
 by_session=defaultdict(list)
 for r in records:
  future=[x for x in snapshots[(r["session"],r["symbol"])] if x["retrieval_ts"]>r["first_eligible_ts"]]
  outcome="PENDING_NO_LATER_SNAPSHOT" if not future else "OBSERVED_NO_THRESHOLD"
  if future and any(x["change_pct"]>=50 for x in future):outcome="OBSERVED_LATER_50"
  elif future and any(x["change_pct"]>=30 for x in future):outcome="OBSERVED_LATER_30"
  by_session[r["session"]].append((r,outcome))
 results={}
 for session,items in sorted(by_session.items()):
  followed=[(r,o) for r,o in items if o!="PENDING_NO_LATER_SNAPSHOT"]
  lanes={}
  for lane in ("baseline","discovery","priority"):
   chosen=[(r,o) for r,o in followed if r[lane]]
   lanes[lane]={"followed":len(chosen),"observed_later30":sum(o in ("OBSERVED_LATER_30","OBSERVED_LATER_50") for r,o in chosen),
    "observed_later50":sum(o=="OBSERVED_LATER_50" for r,o in chosen),
    "no_observed_threshold":sum(o=="OBSERVED_NO_THRESHOLD" for r,o in chosen)}
  results[session]={"candidates":len(items),"followed":len(followed),
   "pending_no_later_snapshot":len(items)-len(followed),"lanes":lanes}
 return {"status":"SHADOW_FORWARD_EVALUATION_NOT_BUY","sessions":results,
 "warning":"Pending means no later snapshot, not a nonwinner. Even observed no threshold is censored if session/data incomplete. This is NOT executable return."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--ledger",required=True)
 a=p.parse_args();print(json.dumps(evaluate(a.db,a.ledger),sort_keys=True))
