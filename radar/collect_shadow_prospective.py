"""Prospective SHADOW cohort ledger: append-only per-session first eligible snapshot.

Reads a frozen real radar-state SQLite checkpoint. Writes JSONL locally; caller
must persist artifact. No live routing modifications, no BUY.
"""
import argparse,json,sqlite3
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

PROTOCOL="shadow-two-lane-v1-2026-10-08"
START_SESSION="2026-10-09"

def collect(db_path,ledger_path,start_session=START_SESSION):
 db=sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 ledger=Path(ledger_path)
 ledger.parent.mkdir(parents=True,exist_ok=True)
 existing={}
 if ledger.exists():
  for line in ledger.read_text().splitlines():
   if not line.strip():continue
   obj=json.loads(line)
   key=(obj["session"],obj["symbol"])
   if key in existing:raise ValueError("duplicate ledger key: "+str(key))
   existing[key]=obj
 first={}
 for r in db.execute("""SELECT session,symbol,retrieval_ts,run_id,change_pct,
 selected,rank_change,rank_turnover FROM scout_history
 WHERE session >= ? ORDER BY session,symbol,retrieval_ts,run_id""",(start_session,)):
  if not 0<=r["change_pct"]<10:continue
  key=(r["session"],r["symbol"])
  if key not in first:first[key]=r
 new=[]
 for (session,symbol),r in sorted(first.items()):
  if (session,symbol) in existing:continue
  wide=r["rank_change"]<=100
  new.append({"protocol":PROTOCOL,"session":session,"symbol":symbol,
   "first_eligible_ts":r["retrieval_ts"],"run_id":r["run_id"],
   "first_change_pct":r["change_pct"],"rank_change":r["rank_change"],
   "rank_turnover":r["rank_turnover"],"baseline":bool(r["selected"]),
   "discovery":wide,"priority":wide and r["rank_turnover"]<=40,
   "status":"PENDING_FORWARD_OUTCOME"})
 if new:
  with ledger.open("a") as f:
   for row in new:f.write(json.dumps(row,sort_keys=True)+"\n")
 return {"status":"SHADOW_LEDGER_COLLECT_NOT_BUY","protocol":PROTOCOL,
  "new_records":len(new),"existing_records":len(existing),
  "first_eligible_in_db":len(first),"start_session":start_session,
  "warning":"Append-only local file: persist to durable storage before claiming monitoring. PENDING outcomes must be evaluated later; never relabel in place."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 p.add_argument("--ledger",required=True);p.add_argument("--start-session",default=START_SESSION)
 a=p.parse_args()
 print(json.dumps(collect(a.db,a.ledger,a.start_session),sort_keys=True))
