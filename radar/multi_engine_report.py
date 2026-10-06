"""Report for SAG-30 parallel SHADOW discovery engines."""
import argparse, json, sqlite3
from pathlib import Path

def _exists(db,name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None

def build(db_path):
    db=sqlite3.connect(db_path); db.row_factory=sqlite3.Row
    try:
        if not _exists(db,"multi_engine_scores"):
            return {"status":"NO_MULTI_ENGINE_DATA","authoritative":False}
        run=db.execute("SELECT MAX(run_id) FROM multi_engine_scores").fetchone()[0]
        if run is None:
            return {"status":"NO_MULTI_ENGINE_DATA","authoritative":False}
        rows=[dict(r) for r in db.execute(
          "SELECT symbol,change_pct,acceleration,impulse,turnover,score,score_rank,high_recall,base_selected,dual_selected "
          "FROM multi_engine_scores WHERE run_id=? ORDER BY score_rank",(run,)
        )]
        pool=db.execute(
          "SELECT COUNT(*),SUM(CASE WHEN seen_count>=2 THEN 1 ELSE 0 END),MAX(seen_count) "
          "FROM multi_engine_watchpool"
        ).fetchone()
        return {
          "status":"MULTI_ENGINE_SHADOW","authoritative":False,"latest_run_id":run,
          "scored_symbols":len(rows),
          "high_recall_count":sum(int(r["high_recall"]) for r in rows),
          "base_selected_in_scored_pool":sum(int(r["base_selected"]) for r in rows),
          "dual_extra_selected":sum(int(r["dual_selected"]) for r in rows),
          "watchpool_symbols":int(pool[0] or 0),
          "persistent_watchpool_symbols":int(pool[1] or 0),
          "max_watchpool_seen_count":int(pool[2] or 0),
          "top_ranker":[r for r in rows[:30]],
          "top_dual_extras":[r for r in rows if int(r["dual_selected"])==1][:30],
          "note":"Research-only. Score weights and high-recall routing are challenger hypotheses; v0.3.3 and r2 gates are unchanged."
        }
    finally:
        db.close()

def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",required=True); p.add_argument("--out",required=True)
    a=p.parse_args(); payload=build(a.db)
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,sort_keys=True))

if __name__=="__main__": main()
