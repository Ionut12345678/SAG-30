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
        raise ValueError("Missing scout_history: cannot report zero signals from absent data")
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
    """Select only after the entire cycle is available, in event-time order.

    A cycle's decision time is its latest retrieval timestamp, never its
    earliest row. Prior completed cycles cannot be overridden by stale rows.
    """
    by_cycle = defaultdict(list)
    by_symbol = defaultdict(list)
    for r in rows:
        if days_before is not None and r["session"] >= days_before:
            continue
        by_cycle[(r["session"], r["run_id"])].append(r)
        by_symbol[(r["session"], r["symbol"])].append(r)
    for history in by_symbol.values():
        history.sort(key=lambda r: (r["stamp"], str(r["run_id"])))
    alerts = {"vnext": [], "simple": []}
    seen = {"vnext": set(), "simple": set()}
    latest_available = {}
    cycles = sorted(by_cycle.items(), key=lambda item: (
        max(r["stamp"] for r in item[1]), item[0][0], str(item[0][1])))
    for cycle, sample in cycles:
        decision_stamp = max(r["stamp"] for r in sample)
        # All candidate features are only known after cycle completion.
        # A later completed cycle must not use an earlier, already superseded
        # observation or a snapshot older than five minutes at decision time.
        eligible = [r for r in sample
                    if 0 <= (decision_stamp - r["stamp"]).total_seconds() <= 300
                    and r["stamp"] > latest_available.get(
                        (r["session"], r["symbol"]),
                        datetime.min.replace(tzinfo=timezone.utc))]
        for strategy in ("vnext", "simple"):
            pool = [r for r in eligible
                    if (r["session"], r["symbol"]) not in seen[strategy]]
            for r in rank_candidates(pool, strategy, cap):
                seen[strategy].add((r["session"], r["symbol"]))
                signal = dict(r)
                signal["decision_stamp"] = decision_stamp
                signal["decision_ts"] = decision_stamp.isoformat()
                alerts[strategy].append(signal)
        for r in sample:
            key = (r["session"], r["symbol"])
            latest_available[key] = max(
                r["stamp"], latest_available.get(
                    key, datetime.min.replace(tzinfo=timezone.utc)))
    return alerts, by_symbol


def summarize(alerts, history, limit_minutes=240):
    """Resolve a negative only after adequate forward sampling.

    Positive sampled threshold hits are evidence even if follow-up ends early.
    A partial/noisy horizon without a hit is *unknown*, never a false positive.
    """
    thresholds = (15, 20, 30, 50)
    cases = []
    for a in alerts:
        future = [r for r in history[(a["session"], a["symbol"])]
                  if r["run_id"] != a["run_id"]
                  and r["stamp"] > a["decision_stamp"]
                  and 0 < (r["stamp"] - a["decision_stamp"]).total_seconds() <= limit_minutes * 60]
        horizon = limit_minutes * 60
        # Tolerate a final sample within 10 minutes of the requested horizon;
        # require <=15-minute gaps from the signal through that final sample.
        stamps = [a["decision_stamp"]] + [r["stamp"] for r in future]
        gaps = [(b - a0).total_seconds() for a0, b in zip(stamps, stamps[1:])]
        complete = bool(future) and (
            (future[-1]["stamp"] - a["decision_stamp"]).total_seconds() >= horizon - min(600, horizon / 10)
            and all(g <= 900 for g in gaps))
        peak = (max(100 * ((100 + r["pct"]) / (100 + a["pct"]) - 1)
                    for r in future) if future else None)
        hits = {str(t): (True if peak is not None and peak >= t
                          else False if complete else None) for t in thresholds}
        status = ("OBSERVED_FULL_HORIZON" if complete else
                  "CENSORED_PARTIAL_HORIZON" if future else
                  "CENSORED_NO_FUTURE_SAMPLE")
        cases.append({"session": a["session"], "symbol": a["symbol"],
                      "first_signal_ts": a["decision_ts"],
                      "first_observation_ts": a["retrieval_ts"],
                      "decision_ts": a["decision_ts"],
                      "signal_change_pct": a["pct"],
                      "entry_price": None, "source_quote_validated": False,
                      "status": status, "forward_horizon_complete": complete,
                      "forward_observation_count": len(future),
                      "max_sampled_return_pct": round(peak, 4) if peak is not None else None,
                      "hits": hits})
    return {"signals": len(cases),
            "with_forward_samples": sum(r["forward_observation_count"] > 0 for r in cases),
            "complete_horizon": sum(r["forward_horizon_complete"] for r in cases),
            "censored": sum(not r["forward_horizon_complete"] for r in cases),
            "hits": {str(t): sum(r["hits"][str(t)] is True for r in cases) for t in thresholds},
            "resolved_by_threshold": {str(t): sum(r["hits"][str(t)] is not None for r in cases)
                                      for t in thresholds},
            "resolved_sampled_hit_rate": {str(t): (
                sum(r["hits"][str(t)] is True for r in cases)
                / sum(r["hits"][str(t)] is not None for r in cases)
                if any(r["hits"][str(t)] is not None for r in cases) else None)
                for t in thresholds},
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
                      "no_future_features": True,
                      "decision_at_cycle_completion": True,
                      "max_observation_age_at_decision_seconds": 300},
            "limitations": [
                "Same source scout_history; unknown source freshness, spread, halt, executable ask.",
                "Decision time is max retrieval timestamp in each cycle; no source-ingest timestamp.",
                "Sampled forward observations can miss highs; incomplete negative follow-up is censored.",
                "Resolved-only hit rates are selection-biased when partial positives are counted.",
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
