"""Export observed multi-engine ranks from durable SAG-30 SQLite state.

Read-only; rank is recorded at scan time in multi_engine_scores, never
reconstructed from best-of-session/winner outcomes. SHADOW only.
"""
import argparse
import json
import sqlite3
from pathlib import Path

def export(db_path):
    db=sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    rows=db.execute("""
      SELECT m.run_id,m.session,m.symbol,m.retrieval_ts,m.change_pct,
             m.score_rank,m.base_selected,m.dual_selected
      FROM multi_engine_scores m
      ORDER BY m.retrieval_ts,m.run_id,m.symbol
    """).fetchall()
    out=[]
    for r in rows:
        out.append({"ts":r["retrieval_ts"],"session":r["session"],
                    "symbol":r["symbol"],"rank":r["score_rank"],
                    "selected":bool(r["base_selected"] or r["dual_selected"]),
                    "base_selected":bool(r["base_selected"]),
                    "dual_selected":bool(r["dual_selected"]),
                    "change_pct":r["change_pct"],"run_id":r["run_id"],
                    "source":"multi_engine_scores",
                    "status":"SHADOW_NOT_BUY"})
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    rows=export(args.db)
    Path(args.out).write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in rows))
    print(json.dumps({"rows":len(rows),"sessions":len({x["session"] for x in rows}),
                      "symbols":len({x["symbol"] for x in rows}),
                      "source":"multi_engine_scores","status":"SHADOW_NOT_BUY"}))
if __name__=="__main__":main()
