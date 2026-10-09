"""Read-only SAG-30 v1.6: sampled returns relative to first eligible SCOUT snapshot.

A scout snapshot is NOT an executable fill, NBBO quote or intrabar high.
This module never writes to SQLite, immutable ledger, FROZEN rules or BUY.
"""
import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HORIZONS = (60, 240)
# Additive sampled research milestones, not executable returns or FROZEN gates.
THRESHOLDS = (10, 15, 20, 30, 50)
LANES = ("baseline", "discovery", "priority")

def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None

def audit(db_path, ledger_path):
    records = [json.loads(line) for line in Path(ledger_path).read_text().splitlines() if line.strip()]
    keys = set()
    for row in records:
        key = (row["session"], row["symbol"])
        if key in keys:
            raise ValueError(f"Duplicate immutable ledger candidate: {key}")
        keys.add(key)
    db = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    samples = defaultdict(list)
    session_end = {}
    try:
        for row in db.execute("SELECT session,symbol,retrieval_ts,change_pct FROM scout_history"):
            t = timestamp(row["retrieval_ts"])
            if t is None:
                continue
            session = row["session"]
            if session not in session_end or t > session_end[session]:
                session_end[session] = t
            key = (session, row["symbol"])
            if key in keys and row["change_pct"] is not None:
                try:
                    pct = float(row["change_pct"])
                    if math.isfinite(pct) and pct > -100:
                        samples[key].append((t, pct))
                except (ValueError, TypeError):
                    pass
    finally:
        db.close()
    for series in samples.values():
        series.sort(key=lambda x: x[0])
    reports = {}
    for horizon in HORIZONS:
        cases = []
        for row in records:
            session, symbol = row["session"], row["symbol"]
            entry = timestamp(row.get("first_eligible_ts"))
            first_pct = row.get("first_change_pct")
            case = {"session": session, "symbol": symbol,
                    "first_eligible_ts": row.get("first_eligible_ts"),
                    "first_change_pct": first_pct,
                    "lanes": [lane for lane in LANES if row.get(lane) is True]}
            try:
                baseline = float(first_pct)
                valid = entry is not None and math.isfinite(baseline) and baseline > -100
            except (TypeError, ValueError):
                valid = False
            if not valid:
                case["status"] = "INVALID_ENTRY"
                cases.append(case)
                continue
            deadline = entry + timedelta(minutes=horizon)
            end = session_end.get(session)
            case["window_complete_in_feed"] = end is not None and end >= deadline
            future = [(t, pct) for t, pct in samples[(session, symbol)] if entry < t <= deadline]
            if not future:
                case["status"] = "NO_FUTURE_SAMPLE" if case["window_complete_in_feed"] else "PENDING_WINDOW"
                cases.append(case)
                continue
            peak_t, peak_pct = max(future, key=lambda x: x[1])
            relative = 100 * ((100 + peak_pct) / (100 + baseline) - 1)
            case.update(status="SAMPLED_COMPLETE" if case["window_complete_in_feed"] else "SAMPLED_PARTIAL",
                        samples=len(future), observed_peak_change_pct=round(peak_pct, 5),
                        observed_peak_ts=peak_t.isoformat(),
                        max_entry_relative_sampled_return_pct=round(relative, 5),
                        **{f"sampled_hit{threshold}_from_entry": relative >= threshold
                           for threshold in THRESHOLDS},
                        **{f"sampled_absolute{threshold}": peak_pct >= threshold
                           for threshold in THRESHOLDS},
                        **{f"first_sampled_hit{threshold}_ts": next(
                            (t.isoformat() for t, pct in future
                             if 100 * ((100 + pct) / (100 + baseline) - 1) >= threshold), None)
                           for threshold in THRESHOLDS})
            cases.append(case)
        def summarize(group):
            observed = [x for x in group if x["status"].startswith("SAMPLED_")]
            complete = [x for x in observed if x["status"] == "SAMPLED_COMPLETE"]
            return {"candidates": len(group), "with_future_samples": len(observed),
                    "complete_window_with_samples": len(complete),
                    "partial_window_with_samples": len(observed) - len(complete),
                    "no_future_sample": sum(x["status"] == "NO_FUTURE_SAMPLE" for x in group),
                    "pending_window": sum(x["status"] == "PENDING_WINDOW" for x in group),
                    "invalid_entry": sum(x["status"] == "INVALID_ENTRY" for x in group),
                    **{f"sampled_entry_relative{threshold}": sum(
                        x[f"sampled_hit{threshold}_from_entry"] for x in observed)
                       for threshold in THRESHOLDS},
                    **{f"sampled_absolute{threshold}": sum(
                        x[f"sampled_absolute{threshold}"] for x in observed)
                       for threshold in THRESHOLDS}}
        by_session = defaultdict(list)
        for case in cases:
            by_session[case["session"]].append(case)
        reports[f"{horizon}m"] = {
            "overall": summarize(cases),
            "lanes": {lane: summarize([x for x in cases if lane in x["lanes"]]) for lane in LANES},
            "sessions": {s: summarize(group) for s, group in sorted(by_session.items())},
            "top_observed_entry_relative": sorted(
                [x for x in cases if x["status"].startswith("SAMPLED_")],
                key=lambda x: x["max_entry_relative_sampled_return_pct"], reverse=True)[:20]}
    return {"version": "SAG30_ENTRY_RELATIVE_SAMPLED_AUDIT_V16",
            "status": "RESEARCH_ONLY_NOT_BUY", "horizons": reports,
            "definition": "100 * ((100 + future scout change_pct)/(100 + first eligible scout change_pct) - 1)",
            "sampled_thresholds_pct": list(THRESHOLDS),
            "warnings": [
                "First eligible SCOUT price is not an executable ask or fill; sampled returns are not trade P&L.",
                "Only strictly later, same-session, within-horizon snapshots; no intrabar high or interpolation.",
                "First sampled crossing timestamps and threshold counts are research observations, not executable entry/exit or guaranteed tradable highs.",
                "SAMPLED_PARTIAL and missing samples are censored, not failures; even COMPLETE means feed window elapsed, not guaranteed continuous coverage.",
                "Lane cohorts overlap; their counts are not independent and must not be summed.",
                "No production BUY, threshold changes, order placement or FROZEN model modifications."]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.db, args.ledger), sort_keys=True))
