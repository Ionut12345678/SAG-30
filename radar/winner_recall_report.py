"""Prospective winner-recall audit for SAG-30 discovery engines.

Primary cohort: symbols observed below +10% before later reaching +30%/+50%.
Secondary benchmark: below +20%.
Research-only; never changes production or candidate gates.
"""
import argparse, json, sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from .research_audit import retention_outcomes, semantic_blockers, semantic_proxy_forward_outcomes
from .proxy_validation import validation as proxy_validation

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
    early_after=[r for r in after if isinstance(r["change_pct"],(int,float)) and r["change_pct"]<ceiling]
    if not early_after:
        return "DEEP_TIMING_MISS",first,deep,None
    if all(int(r["baseline_samples"] or 0)<5 for r in early_after):
        return "BASELINE_MISS",first,deep,None
    return "MODEL_MISS",first,deep,None

def _baseline_diagnostic(rows, deep, target_ts, ceiling=10):
    """Explain pre-target baseline coverage without changing model gates.

    All timestamps come from recorded retrievals. Never infer a tradable entry.
    """
    selected = [r for r in rows if r["retrieval_ts"] < target_ts
                and float(r["change_pct"]) < ceiling
                and int(r.get("selected") or 0) == 1]
    if not selected:
        return None
    first_selected = min(r["retrieval_ts"] for r in selected)
    before_target = [r for r in deep if first_selected <= r["retrieval_ts"] < target_ts]
    early_deep = [r for r in before_target if isinstance(r["change_pct"], (int, float))
                  and r["change_pct"] < ceiling]
    sample_counts = [int(r["baseline_samples"] or 0) for r in early_deep]
    return {
        "status": "DIAGNOSTIC_SHADOW_NOT_BUY",
        "first_selected_ts": first_selected,
        "first_early_deep_ts": early_deep[0]["retrieval_ts"] if early_deep else None,
        "early_deep_observations": len(early_deep),
        "max_early_baseline_samples": max(sample_counts) if sample_counts else None,
        "baseline_requirement_samples": 5,
        "early_deep_states": sorted(set(r["state"] for r in early_deep)),
        "reason": ("NO_EARLY_DEEP_OBSERVATION" if not early_deep else
                   "INSUFFICIENT_EARLY_BASELINE" if max(sample_counts) < 5 else
                   "EARLY_BASELINE_PRESENT_CHECK_OTHER_GATES"),
        "note": "Prospective retrieval timestamps only; no implied execution or BUY.",
    }

def _early_shortlist_outcomes(groups, now=None):
    """Forward-only cohort with a denominator, including non-winners.

    A candidate enters only at its first observed selected <+10% snapshot,
    provided no +30% observation preceded it in that session. Open sessions
    are PENDING and excluded from finalized precision statistics.
    """
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(ZoneInfo("America/New_York"))
    today = et.date().isoformat()
    finalized = 0
    hit30 = 0
    hit50 = 0
    pending = 0
    cases = []
    for (session, symbol), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda r: r["retrieval_ts"])
        first = next((i for i, r in enumerate(rows)
                      if int(r.get("selected") or 0) == 1
                      and -10 <= float(r["change_pct"]) < 10
                      and not any(float(p["change_pct"]) >= 30 for p in rows[:i])), None)
        if first is None:
            continue
        entry = rows[first]
        future = [r for r in rows[first + 1:]
                  if r["retrieval_ts"] > entry["retrieval_ts"]]
        first30 = _first_target(future, 30)
        first50 = _first_target(future, 50)
        closed = session < today or (session == today and et.hour >= 20)
        if closed:
            finalized += 1
            hit30 += int(first30 is not None)
            hit50 += int(first50 is not None)
        else:
            pending += 1
        cases.append({
            "session": session, "symbol": symbol,
            "status": "FINALIZED" if closed else "PENDING_SESSION_CLOSE",
            "first_selected_ts": entry["retrieval_ts"],
            "first_selected_pct": entry["change_pct"],
            "first_observed_30_after_selection_ts": first30["retrieval_ts"] if first30 else None,
            "first_observed_50_after_selection_ts": first50["retrieval_ts"] if first50 else None,
            "last_observed_pct": rows[-1]["change_pct"],
        })
    return {
        "status": "SHADOW_PROSPECTIVE_NOT_BUY",
        "note": "Scout-selected denominator; no execution assumptions. Pending sessions excluded from finalized precision. Recorded snapshots may miss intracycle highs.",
        "finalized_selected_sessions": finalized,
        "pending_selected_sessions": pending,
        "finalized_observed_30_after_selection": hit30,
        "finalized_observed_50_after_selection": hit50,
        "observed_30_rate_finalized": hit30 / finalized if finalized else None,
        "observed_50_rate_finalized": hit50 / finalized if finalized else None,
        "cases": cases[-300:],
    }

def _retention_shadow_replay(groups, windows=(60, 180, 360), caps=(5, 10)):
    """Counterfactual *routing workload*, not historical model evaluations.

    A symbol must have been selected below +10% earlier in the same session.
    Only current observed sub-10% unselected snapshots can be shadow-retained.
    Rank by last selection timestamp, never by future winner status.
    """
    from collections import defaultdict
    from datetime import datetime
    by_session=defaultdict(lambda:defaultdict(list))
    for (session,symbol),rows in groups.items():
        for r in rows:
            by_session[session][r["run_id"]].append((symbol,r))
    results=[]
    for minutes in windows:
        for cap in caps:
            extra=0
            total_cycles=0
            nonempty_cycles=0
            max_per_cycle=0
            opportunity30=set()
            opportunity50=set()
            all_held=set()
            for session,runs in by_session.items():
                last_selected={}
                already30=set()
                for run_id,entries in sorted(runs.items()):
                    total_cycles+=1
                    # Rows in the same run are one snapshot, not sequential predictions.
                    current={symbol:r for symbol,r in entries}
                    for symbol,r in entries:
                        if float(r["change_pct"])>=30:
                            already30.add(symbol)
                    candidates=[]
                    for symbol,r in entries:
                        pct=float(r["change_pct"])
                        if int(r.get("selected") or 0)==1 and -10<=pct<10 and symbol not in already30:
                            last_selected[symbol]=r["retrieval_ts"]
                    for symbol,r in entries:
                        pct=float(r["change_pct"])
                        if symbol in already30 or not (-10<=pct<10) or int(r.get("selected") or 0)==1:
                            continue
                        prev=last_selected.get(symbol)
                        if not prev:
                            continue
                        age=(datetime.fromisoformat(r["retrieval_ts"])-datetime.fromisoformat(prev)).total_seconds()/60
                        if 0<=age<=minutes:
                            candidates.append((prev,symbol,r))
                    candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
                    chosen=candidates[:cap]
                    extra+=len(chosen)
                    nonempty_cycles+=int(bool(chosen))
                    max_per_cycle=max(max_per_cycle,len(chosen))
                    for _,symbol,r in chosen:
                        all_held.add((session,symbol))
                        # Labels below are outcomes, not used in selection/ranking.
                        future=[x for x in groups[(session,symbol)] if x["retrieval_ts"]>r["retrieval_ts"]]
                        if _first_target(future,30):
                            opportunity30.add((session,symbol))
                        if _first_target(future,50):
                            opportunity50.add((session,symbol))
            results.append({
                "retention_minutes":minutes,"extra_slots_per_cycle_cap":cap,
                "scout_cycles":total_cycles,"extra_deep_observation_slots":extra,
                "cycles_with_extra_slots":nonempty_cycles,
                "mean_extra_slots_per_cycle":extra/total_cycles if total_cycles else None,
                "max_extra_slots_in_cycle":max_per_cycle,
                "unique_held_symbol_sessions":len(all_held),
                "held_with_later_observed_30":len(opportunity30),
                "held_with_later_observed_50":len(opportunity50),
            })
    return {
        "status":"COUNTERFACTUAL_SHADOW_ROUTING_ONLY_NOT_BUY",
        "note":"Replays recorded scout snapshots only. Extra slots are hypothetical; no missing deep bars are reconstructed, no executable price or BUY is implied. Unobserved candidates and actual provider cost are not measured. Later +30/+50 labels are outcomes, never selection features.",
        "scenarios":results,
    }

def _retention_live_summary(db):
    if not _exists(db,"retention_shadow_observations"):
        return {"status":"NOT_STARTED","observations":0,"fresh":0,"data_gap":0}
    rows=db.execute(
        "SELECT run_id,session,symbol,selected_ts,scout_pct,observed_ts,source_ts,"
        "source_age_seconds,deep_price,feed,status "
        "FROM retention_shadow_observations ORDER BY run_id DESC,symbol LIMIT 100"
    ).fetchall()
    counts=dict(db.execute(
        "SELECT status,COUNT(*) FROM retention_shadow_observations GROUP BY status"
    ).fetchall())
    return {
        "status":"LIVE_SHADOW_NOT_BUY","observations":sum(counts.values()),
        "fresh":counts.get("SHADOW_FRESH_TRADE",0),
        "data_gap":counts.get("SHADOW_DATA_GAP",0),
        "fetch_error":counts.get("SHADOW_FETCH_ERROR",0),
        "recent":[dict(r) for r in rows],
        "note":"Independent snapshot lane. Never feeds production candidate, frozen gates or BUY."
    }

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
              "baseline_diagnostic_under_10":_baseline_diagnostic(rows,deep10,t30["retrieval_ts"]),
            })
        winners.sort(key=lambda r:(not r["reached_50"],r["first_30_ts"]))
        total=len(winners)
        def frac(pred):
            return sum(1 for r in winners if pred(r))/total if total else None
        proxy_full=semantic_proxy_forward_outcomes(db,case_limit=None)
        proxy_guardrails=proxy_validation(proxy_full)
        proxy_full["cases"]=proxy_full.get("cases",[])[-200:]
        return {
          "status":"WINNER_RECALL_AUDIT","authoritative":False,
          "primary_entry_ceiling_pct":10,
          "secondary_entry_ceiling_pct":20,
          "scope":"Only prospective sessions recorded after full-universe scout_history deployment.",
          "early_shortlist_outcomes":_early_shortlist_outcomes(groups),
          "retention_shadow_replay":_retention_shadow_replay(groups),
          "retention_live_challenger":_retention_live_summary(db),
          "retention_prospective_outcomes":retention_outcomes(db),
          "semantic_blocker_diagnostics":semantic_blockers(db),
          "semantic_proxy_forward_outcomes":proxy_full,
          "semantic_proxy_validation":proxy_guardrails,
          "winner_sessions":total,
          "winner_50_sessions":sum(1 for r in winners if r["reached_50"]),
          "classification_counts_under_10":counts10,
          "classification_counts_under_20":counts20,
          "baseline_miss_diagnostics_under_10":[{"session":r["session"],"symbol":r["symbol"],**r["baseline_diagnostic_under_10"]} for r in winners if r["classification_under_10"]=="BASELINE_MISS" and r["baseline_diagnostic_under_10"] is not None],
          "deep_timing_miss_diagnostics_under_10":[{"session":r["session"],"symbol":r["symbol"],**r["baseline_diagnostic_under_10"]} for r in winners if r["classification_under_10"]=="DEEP_TIMING_MISS" and r["baseline_diagnostic_under_10"] is not None],
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
