"""Research report for SAG-30 v0.3.4 CANDIDATE SHADOW."""
import argparse, json, sqlite3
from pathlib import Path

def _table_exists(db,name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None

def build(db_path):
    db=sqlite3.connect(db_path)
    try:
        if not _table_exists(db,"candidate_v034_events"):
            return {"status":"NO_CANDIDATE_DATA","authoritative":False}
        states=dict(db.execute("SELECT state,COUNT(*) FROM candidate_v034_events GROUP BY state").fetchall())
        lanes=dict(db.execute("SELECT lane,COUNT(*) FROM candidate_v034_events GROUP BY lane").fetchall())
        signals=db.execute("SELECT id,symbol,retrieval_ts,lane,state,change_pct,proof FROM candidate_v034_signals ORDER BY id").fetchall() if _table_exists(db,"candidate_v034_signals") else []
        milestone_counts={30:0,50:0}
        if _table_exists(db,"candidate_v034_milestones"):
            for target,count in db.execute("SELECT target,COUNT(DISTINCT signal_id) FROM candidate_v034_milestones GROUP BY target"):
                milestone_counts[int(target)]=int(count)
        signal_rows=[
          {"id":r[0],"symbol":r[1],"retrieval_ts":r[2],"lane":r[3],"state":r[4],"change_pct":r[5],"proof":r[6]}
          for r in signals[-50:]
        ]
        watch=db.execute("SELECT COUNT(*),AVG(first_watch_pct) FROM candidate_v034_state WHERE first_watch_ts IS NOT NULL").fetchone()
        baseline=db.execute(
          "SELECT COUNT(*),SUM(CASE WHEN baseline_samples>=5 THEN 1 ELSE 0 END),"
          "SUM(CASE WHEN rvol>=3 THEN 1 ELSE 0 END),SUM(CASE WHEN rvol>=10 THEN 1 ELSE 0 END) "
          "FROM candidate_v034_events"
        ).fetchone()
        return {
          "status":"CANDIDATE_SHADOW_ONLY",
          "authoritative":False,
          "version":"SAG-30 v0.3.4 CANDIDATE SHADOW rev1",
          "events":sum(states.values()),
          "states":states,
          "lanes":lanes,
          "baseline":{
            "events_with_candidate_valid_sample_count":int(baseline[1] or 0),
            "events_rvol_ge_3":int(baseline[2] or 0),
            "events_rvol_ge_10_saturated":int(baseline[3] or 0)
          },
          "first_watch":{
            "symbols":int(watch[0] or 0),
            "mean_pct":watch[1]
          },
          "signals":{
            "total":len(signals),
            "plus_30_reached":milestone_counts[30],
            "plus_50_reached":milestone_counts[50],
            "recent":signal_rows
          },
          "warning":"Research-only candidate. v0.3.3 FROZEN remains authoritative; no production alerts are emitted."
        }
    finally:
        db.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True); p.add_argument("--out",required=True)
    a=p.parse_args()
    payload=build(a.db)
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,sort_keys=True))

if __name__=="__main__":
    main()
