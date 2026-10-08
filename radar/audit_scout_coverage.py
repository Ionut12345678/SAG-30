"""Read-only prospective SCOUT full-cohort vs multi-engine coverage audit.

No forward returns, no inferred rank, no BUY.
"""
import argparse
import json
import sqlite3
from pathlib import Path

def audit(path):
    db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    scout=db.execute("""SELECT run_id,session,symbol,retrieval_ts,change_pct,
         rank_change,rank_acceleration,rank_impulse,rank_turnover,selected,sticky
         FROM scout_history""").fetchall()
    multi=db.execute("""SELECT run_id,symbol,score_rank,base_selected,dual_selected
         FROM multi_engine_scores""").fetchall()
    keys={(r["run_id"],r["symbol"]) for r in scout}
    multi_keys={(r["run_id"],r["symbol"]) for r in multi}
    assert len(keys)==len(scout),"Duplicate SCOUT run-symbol"
    assert len(multi_keys)==len(multi),"Duplicate multi-engine run-symbol"
    assert all(all(isinstance(r[k],int) and r[k]>0 for k in
          ("rank_change","rank_acceleration","rank_impulse","rank_turnover")) for r in scout)
    missing=multi_keys-keys
    assert not missing,f"Multi-engine rows absent from SCOUT: {len(missing)}"
    scout_selected={
        (r["run_id"],r["symbol"]) for r in scout if r["selected"]}
    multi_selected={(r["run_id"],r["symbol"]) for r in multi
                    if r["base_selected"] or r["dual_selected"]}
    return {
       "status":"PASS","source":"radar-state SQLite",
       "scout_rows":len(scout),"multi_engine_rows":len(multi),
       "scout_only_rows":len(keys-multi_keys),
       "multi_engine_coverage_pct":round(100*len(multi_keys)/len(keys),2) if keys else None,
       "scout_selected_rows":len(scout_selected),
       "multi_engine_selected_rows":len(multi_selected),
       "sessions":len({r["session"] for r in scout}),
       "note":"Observed routing ranks only. No forward outcomes, fill simulation or BUY."}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    args=p.parse_args()
    print(json.dumps(audit(args.db),sort_keys=True))
if __name__=="__main__":main()
