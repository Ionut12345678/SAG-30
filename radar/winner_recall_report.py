"""Prospective winner-recall audit for SAG-30 discovery engines.

Primary cohort: symbols observed below +10% before later reaching +30%/+50%.
Secondary benchmark: below +20%.
Research-only; never changes production or candidate gates.
"""
import argparse, json, sqlite3
from pathlib import Path

def _exists(db,name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None

def _first_target(rows,target):
    return next((r for r in rows if float(r["change_pct"])>=target),None)

def _best_rank(rows,key):
    vals=[int(r[key]) for r in rows if r.get(key) is not None]
    return min(vals) if vals else None

def _deep_r2(db,symbol,session,before_ts):
    if not _exists(db,"candidate_v034r2_events"):
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

def _classify(db,symbol,session,rows,target_row,ceiling):
    before=[r for r in rows if r["retrieval_ts"]<target_row["retrieval_ts"]]
    early=[r for r in before if float(r["change_pct"])<ceiling]
    if not early:
        return "SCOUT_MISS",None,[],None
    selected=[r for r in early if int(r.get("selected") or 0)==1]
    first=early[0]
    if not selected:
        return "SHORTLIST_MISS",first,[],None
    deep=_deep_r2(db,symbol,session,target_row["retrieval_ts"])
    hot=next((r for r in deep if r["state"]=="C34R2-HOT-SHADOW" and isinstance(r["change_pct"],(int,float)) and r["change_pct"]<ceiling),None)
    if hot:
        return "EARLY_HOT_SUCCESS",first,deep,hot
    first_sel=min(r["retrieval_ts"] for r in selected)
    after=[r for r in deep if r["retrieval_ts"]>=first_sel]
    if not after:
        return "DEEP_MISS",first,deep,None
    if all(int(r["baseline_samples"] or 0)<5 for r in after):
        return "BASELINE_MISS",first,deep,None
    return "MODEL_MISS",first,deep,None

def build(db_path):
    db=sqlite3.connect(db_path); db.row_factory=sqlite3.Row
    try:
        if not _exists(db,"scout_history"):
            return {"status":"NO_FULL_UNIVERSE_HISTORY","authoritative":False}
        has_multi=_exists(db,"multi_engine_scores")
        join=(
          "LEFT JOIN multi_engine_scores m ON m.run_id=h.run_id AND m.symbol=h.symbol"
          if has_multi else
          "LEFT JOIN (SELECT NULL run_id,NULL symbol,NULL base_selected,NULL dual_selected,NULL score,NULL score_rank) m ON 1=0"
        )
        raw=db.execute(
          "SELECT h.run_id,h.session,h.symbol,h.retrieval_ts,h.change_pct,h.rank_change,h.rank_acceleration,"
          "h.rank_impulse,h.rank_turnover,h.selected,"
          "COALESCE(m.base_selected,0) base_selected,COALESCE(m.dual_selected,0) dual_selected,"
          "m.score,m.score_rank FROM scout_history h "+join+
          " ORDER BY h.session,h.symbol,h.retrieval_ts"
        ).fetchall()
        groups={}
        for x in raw:
            r=dict(x); groups.setdefault((r["session"],r["symbol"]),[]).append(r)

        winners=[]; counts10={}; counts20={}
        for (session,symbol),rows in groups.items():
            t30=_first_target(rows,30)
            if not t30: continue
            t50=_first_target(rows,50)
            cls10,first10,deep10,hot10=_classify(db,symbol,session,rows,t30,10)
            cls20,first20,deep20,hot20=_classify(db,symbol,session,rows,t30,20)
            counts10[cls10]=counts10.get(cls10,0)+1
            counts20[cls20]=counts20.get(cls20,0)+1
            pre10=[r for r in rows if r["retrieval_ts"]<t30["retrieval_ts"] and float(r["change_pct"])<10]
            base10=[r for r in pre10 if int(r.get("base_selected") or 0)==1]
            dual10=[r for r in pre10 if int(r.get("dual_selected") or 0)==1]
            selected10=[r for r in pre10 if int(r.get("selected") or 0)==1]
            winners.append({
              "session":session,"symbol":symbol,"reached_50":t50 is not None,
              "first_30_ts":t30["retrieval_ts"],"first_30_pct":t30["change_pct"],
              "first_50_ts":t50["retrieval_ts"] if t50 else None,
              "classification_under_10":cls10,"classification_under_20":cls20,
              "first_under_10_scout_ts":first10["retrieval_ts"] if first10 else None,
              "first_under_10_scout_pct":first10["change_pct"] if first10 else None,
              "base_selected_under_10":bool(base10),
              "dual_extra_selected_under_10":bool(dual10),
              "any_selected_under_10":bool(selected10),
              "best_pre30_rank_change_under_10":_best_rank(pre10,"rank_change"),
              "best_pre30_rank_acceleration_under_10":_best_rank(pre10,"rank_acceleration"),
              "best_pre30_rank_impulse_under_10":_best_rank(pre10,"rank_impulse"),
              "best_pre30_rank_turnover_under_10":_best_rank(pre10,"rank_turnover"),
              "best_multi_engine_score_under_10":max([float(r["score"]) for r in pre10 if r.get("score") is not None],default=None),
              "best_multi_engine_rank_under_10":min([int(r["score_rank"]) for r in pre10 if r.get("score_rank") is not None],default=None),
              "r2_hot_under_10_ts":hot10["retrieval_ts"] if hot10 else None,
              "r2_hot_under_10_pct":hot10["change_pct"] if hot10 else None,
              "r2_path_before_30":deep10[-12:],
            })
        winners.sort(key=lambda r:(not r["reached_50"],r["first_30_ts"]))
        total=len(winners)
        def frac(pred):
            return sum(1 for r in winners if pred(r))/total if total else None
        return {
          "status":"WINNER_RECALL_AUDIT","authoritative":False,
          "primary_entry_ceiling_pct":10,
          "secondary_entry_ceiling_pct":20,
          "scope":"Only prospective sessions recorded after full-universe scout_history deployment.",
          "winner_sessions":total,
          "winner_50_sessions":sum(1 for r in winners if r["reached_50"]),
          "classification_counts_under_10":counts10,
          "classification_counts_under_20":counts20,
          "under_10_scout_recall":frac(lambda r:r["first_under_10_scout_ts"] is not None),
          "under_10_base_shortlist_recall":frac(lambda r:r["base_selected_under_10"]),
          "under_10_dual_extra_recall":frac(lambda r:r["dual_extra_selected_under_10"]),
          "under_10_any_shortlist_recall":frac(lambda r:r["any_selected_under_10"]),
          "under_10_r2_hot_recall":frac(lambda r:r["r2_hot_under_10_ts"] is not None),
          "winners":winners[:200],
        }
    finally:
        db.close()

def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",required=True); p.add_argument("--out",required=True)
    a=p.parse_args(); payload=build(a.db)
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,sort_keys=True))

if __name__=="__main__": main()
