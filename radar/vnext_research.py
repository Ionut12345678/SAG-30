"""Independent SAG-30 vNext research radar: observed scout data only, never BUY.

Strict chronological replay. It reads the original scout_history without modifying
it, uses no future feature in selection, and evaluates sampled outcomes afterwards.
No quote/ask availability: results are NOT executable returns.
"""
import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _parse(ts):
    try:
        value = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (TypeError, ValueError, AttributeError):
        return None


def load(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='scout_history' AND type='table'").fetchone():
        return []
    rows = db.execute(
        "SELECT run_id,session,symbol,retrieval_ts,change_pct,"
        "acceleration_pp_per_min,fresh_turnover_impulse_per_min,turnover,selected "
        "FROM scout_history ORDER BY session,run_id,symbol"
    ).fetchall()
    output = []
    for row in rows:
        run, session, symbol, ts, pct, accel, impulse, turnover, selected = row
        stamp = _parse(ts)
        features = (pct, accel, impulse, turnover)
        if stamp is None or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in features):
            continue
        output.append(dict(run_id=run, session=session, symbol=symbol, retrieval_ts=ts,
                           stamp=stamp, pct=float(pct), accel=float(accel),
                           impulse=float(impulse), turnover=float(turnover),
                           selected=int(selected)))
    return output


def rank_candidates(rows, strategy, limit):
    """Same-cycle rankings: no outcome labels, future observations or retrodated timestamps."""
    if strategy == "vnext":
        pool = [r for r in rows if -2 <= r["pct"] < 10 and r["accel"] > 0
                and r["impulse"] > 0 and r["turnover"] > 0]
        return sorted(pool, key=lambda r: (
            -min(r["accel"], 5), -min(r["impulse"], 1),
            -min(r["turnover"], 1), r["symbol"]))[:limit]
    if strategy == "simple":
        pool = [r for r in rows if 5 <= r["pct"] < 10]
        return sorted(pool, key=lambda r: (-r["pct"], r["symbol"]))[:limit]
    raise ValueError(strategy)


def replay(rows, cap=3, days_before=None):
    """Once-per-symbol/session alert; both strategies have equal per-run capacity."""
    by_cycle = defaultdict(list)
    by_symbol = defaultdict(list)
    for r in rows:
        if days_before is not None and r["session"] >= days_before:
            continue
        by_cycle[(r["session"], r["run_id"])].append(r)
        by_symbol[(r["session"], r["symbol"])].append(r)
    for history in by_symbol.values():
        history.sort(key=lambda r: (r["stamp"], r["run_id"]))
    alerts = {"vnext": [], "simple": []}
    seen = {"vnext": set(), "simple": set()}
    for cycle in sorted(by_cycle):
        sample = by_cycle[cycle]
        for strategy in ("vnext", "simple"):
            pool = [r for r in sample if (r["session"], r["symbol"]) not in seen[strategy]]
            for r in rank_candidates(pool, strategy, cap):
                seen[strategy].add((r["session"], r["symbol"]))
                alerts[strategy].append(r)
    return alerts, by_symbol


def summarize(alerts, history, limit_minutes=240):
    cases = []
    for a in alerts:
        future = [r for r in history[(a["session"], a["symbol"])]
                  if r["stamp"] > a["stamp"]
                  and 0 < (r["stamp"] - a["stamp"]).total_seconds() <= limit_minutes * 60]
        if not future:
            status, peak, hits = "CENSORED_NO_FUTURE_SAMPLE", None, None
        else:
            peak = max(100 * ((100 + r["pct"]) / (100 + a["pct"]) - 1)
                       for r in future if a["pct"] > -100)
            hits = {str(t): peak >= t for t in (15, 20, 30, 50)}
            status = "OBSERVED_SAMPLED"
        cases.append({"session": a["session"], "symbol": a["symbol"],
                      "first_signal_ts": a["retrieval_ts"], "signal_change_pct": a["pct"],
                      "entry_price": None, "source_quote_validated": False,
                      "status": status, "forward_observation_count": len(future),
                      "max_sampled_return_pct": round(peak, 4) if peak is not None else None,
                      "hits": hits})
    observed = [r for r in cases if r["status"] == "OBSERVED_SAMPLED"]
    return {"signals": len(cases), "with_forward_samples": len(observed),
            "censored": len(cases) - len(observed),
            "hits": {str(t): sum(r["hits"][str(t)] for r in observed)
                     for t in (15, 20, 30, 50)},
            "precision_observed_only": {str(t): (
                sum(r["hits"][str(t)] for r in observed) / len(observed)
                if observed else None) for t in (15, 20, 30, 50)},
            "cases": cases}


def build(db, cap=3, minutes=240, exclude_open_session=True):
    rows = load(db)
    # Date-only conservative exclusion: do not finalize same-day outcomes.
    cutoff = datetime.now(timezone.utc).date().isoformat() if exclude_open_session else None
    alerts, history = replay(rows, cap, cutoff)
    return {"version": "SAG30_VNEXT_V0_RESEARCH_ONLY",
            "status": "SHADOW_NOT_BUY",
            "rules": {"max_new_alerts_per_cycle": cap,
                      "forward_minutes": minutes, "exclude_utc_today": exclude_open_session,
                      "no_future_features": True},
            "limitations": [
                "Same source scout_history; unknown source freshness, spread, halt, executable ask.",
                "Sampled forward observations can miss highs; censored candidates are not losses.",
                "Backtest is in-sample research, not independent out-of-sample validation.",
                "Equal alert budget per cycle, but differing eligibility and signal counts.",
                "No real-time connection, production workflow change, or frozen BUY decision."],
            "strategies": {k: summarize(v, history, minutes) for k, v in alerts.items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cap", type=int, default=3)
    parser.add_argument("--minutes", type=int, default=240)
    args = parser.parse_args()
    if not 1 <= args.cap <= 20 or not 1 <= args.minutes <= 1440:
        parser.error("cap must be 1..20 and minutes 1..1440")
    with sqlite3.connect(args.db) as db:
        result = build(db, args.cap, args.minutes)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
