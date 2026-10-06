"""Prospective winner recall audit for SAG-30 FAST SCOUT.

Research-only. Classifies where later +30/+50 winners were lost:
SCOUT_MISS, SHORTLIST_MISS, BASELINE_MISS, MODEL_MISS, or EARLY_HOT_SUCCESS.
"""
import argparse, json, sqlite3
from pathlib import Path

def _table_exists(db,name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None

def _first_target(rows,target):
    for row in rows:
        if float(row["change_pct"])>=target:
            return row
    return None

def _best_rank(rows,key):
    vals=[int(r[key]) for r in rows if r.get(key) is not None]
    return min(vals) if vals else None

def _deep_r2(db,symbol,session,before_ts):
    if not _table_exists(db,"candidate_v034r2_events"):
        return []
    rows=db.execute(
      "SELECT c.state,c.change_pct,c.rvol,c.baseline_samples,c.detail,o.retrieval_ts "
      "FROM candidate_v034r2_events c JOIN observations o ON o.id=c.observation_id "
      "WHERE c.symbol=? AND c.session=? AND o.retrieval_ts<? ORDER BY o.retrieval_ts",
      (symbol,session,before_ts)
    ).fetchall()
    return [
      {"state":r[0],"change_pct":r[1],"rvol":r[2],"baseline_samples":r[3],"detail":r[4],"retrieval_ts":r[5]}
      for r in rows
    ]

def _classify(db,symbol,session,rows,target_row):
    before=[r for r in rows if r["retrieval_ts"]<target_row["retrieval_ts"]]
    early=[r for r in before if float(r["change_pct"])<20]
    if not early:
        return "SCOUT_MISS",None,[]
    selected_early=[r for r in early if int(r["selected"])==1]
    first_early=early[0]
    if not selected_early:
        return "SHORTLIST_MISS",first_early,[]
    deep=_deep_r2(db,symbol,session,target_row["retrieval_ts"])
    hot=[r for r in deep if r["state"]=="C34R2-HOT-SHADOW" and isinstance(r["change_pct"],(int,float)) and r["change_pct"]<20]
    if hot:
        return "EARLY_HOT_SUCCESS",first_early,deep
    selected_ts=min(r["retrieval_ts"] for r in selected_early)
    after_selected=[r for r in deep if r["retrieval_ts"]>=selected_ts]
    if not after_selected:
        return "DEEP_MISS",first_early,deep
    if all(int(r["baseline_samples"] or 0)<5 for r in after_selected):
        return "BASELINE_MISS",first_early,deep
    return "MODEL_MISS",first_early,deep

def build(db_path):
    db=sqlite3.connect(db_path)
    db.row_factory=sqlite3.Row
    try:
        if not _table_exists(db,"scout_history"):
            return {
              "status":"NO_FULL_UNIVERSE_HISTORY",
              "authoritative":False,
              "detail":"Full-universe scout history starts only after Winner Recall Audit deployment."
            }
        raw=db.execute(
          "SELECT session,symbol,retrieval_ts,change_pct,acceleration_pp_per_min,fresh_turnover_impulse_per_min,"
          "turnover,rank_change,rank_acceleration,rank_impulse,rank_turnover,selected,sticky "
          "FROM scout_history ORDER BY session,symbol,retrieval_ts"
        ).fetchall()
        groups={}
        for x in raw:
            r=dict(x)
            groups.setdefault((r["session"],r["symbol"]),[]).append(r)

        winners=[]
        counts={}
        for (session,symbol),rows in groups.items():
            t30=_first_target(rows,30)
            if not t30:
                continue
            t50=_first_target(rows,50)
            cls,first_early,deep=_classify(db,symbol,session,rows,t30)
            counts[cls]=counts.get(cls,0)+1
            early=[r for r in rows if r["retrieval_ts"]<t30["retrieval_ts"] and float(r["change_pct"])<20]
            selected_early=[r for r in early if int(r["selected"])==1]
            first_selected=selected_early[0] if selected_early else None
            hot=next((r for r in deep if r["state"]=="C34R2-HOT-SHADOW" and isinstance(r["change_pct"],(int,float)) and r["change_pct"]<20),None)
            winners.append({
              "session":session,
              "symbol":symbol,
              "reached_50":t50 is not None,
              "first_30_ts":t30["retrieval_ts"],
              "first_30_pct":t30["change_pct"],
              "first_50_ts":t50["retrieval_ts"] if t50 else None,
              "classification":cls,
              "first_early_scout_ts":first_early["retrieval_ts"] if first_early else None,
              "first_early_scout_pct":first_early["change_pct"] if first_early else None,
              "first_selected_ts":first_selected["retrieval_ts"] if first_selected else None,
              "first_selected_pct":first_selected["change_pct"] if first_selected else None,
              "best_pre30_rank_change":_best_rank(early,"rank_change"),
              "best_pre30_rank_acceleration":_best_rank(early,"rank_acceleration"),
              "best_pre30_rank_impulse":_best_rank(early,"rank_impulse"),
              "best_pre30_rank_turnover":_best_rank(early,"rank_turnover"),
              "r2_hot_ts":hot["retrieval_ts"] if hot else None,
              "r2_hot_pct":hot["change_pct"] if hot else None,
              "r2_path_before_30":deep[-12:],
            })
        winners.sort(key=lambda r:(not r["reached_50"],r["first_30_ts"]))
        total=len(winners)
        return {
          "status":"WINNER_RECALL_AUDIT",
          "authoritative":False,
          "scope":"Only sessions recorded in scout_history; earlier sessions are not reconstructable from full-universe data.",
          "winner_sessions":total,
          "winner_50_sessions":sum(1 for r in winners if r["reached_50"]),
          "classification_counts":counts,
          "early_scout_recall":sum(1 for r in winners if r["first_early_scout_ts"] is not None)/total if total else None,
          "early_shortlist_recall":sum(1 for r in winners if r["first_selected_ts"] is not None)/total if total else None,
          "early_r2_hot_recall":sum(1 for r in winners if r["r2_hot_ts"] is not None)/total if total else None,
          "winners":winners[:200],
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
