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
# Same-cycle subsecond records are not independently actionable later observations.
MIN_INDEPENDENT_OBSERVATION_LAG = timedelta(seconds=1)
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
            future = [(t, pct) for t, pct in samples[(session, symbol)]
                      if entry + MIN_INDEPENDENT_OBSERVATION_LAG <= t <= deadline]
            same_cycle = sum(entry < t < entry + MIN_INDEPENDENT_OBSERVATION_LAG
                             for t, pct in samples[(session, symbol)])
            case["excluded_subsecond_observations"] = same_cycle
            if not future:
                case["status"] = ("UNVERIFIED_SAME_CYCLE_ONLY" if same_cycle else
                                  "NO_FUTURE_SAMPLE" if case["window_complete_in_feed"] else "PENDING_WINDOW")
                cases.append(case)
                continue
            peak_t, peak_pct = max(future, key=lambda x: x[1])
            relative = 100 * ((100 + peak_pct) / (100 + baseline) - 1)
            case.update(status="SAMPLED_COMPLETE" if case["window_complete_in_feed"] else "SAMPLED_PARTIAL",
                        samples=len(future), observed_peak_change_pct=round(peak_pct, 5),
                        observed_peak_ts=peak_t.isoformat(),
                        max_entry_relative_sampled_return_pct=round(relative, 5),
                        sampled_hit30_from_entry=relative >= 30,
                        sampled_hit50_from_entry=relative >= 50,
                        sampled_absolute30=peak_pct >= 30,
                        sampled_absolute50=peak_pct >= 50)
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
                    "unverified_same_cycle_only": sum(x["status"] == "UNVERIFIED_SAME_CYCLE_ONLY" for x in group),
                    "sampled_entry_relative30": sum(x["sampled_hit30_from_entry"] for x in observed),
                    "sampled_entry_relative50": sum(x["sampled_hit50_from_entry"] for x in observed),
                    "sampled_absolute30": sum(x["sampled_absolute30"] for x in observed),
                    "sampled_absolute50": sum(x["sampled_absolute50"] for x in observed)}
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
            "warnings": [
                "First eligible SCOUT price is not an executable ask or fill; sampled returns are not trade P&L.",
                "Only independently later (at least 1 second), same-session, within-horizon snapshots; subsecond same-cycle duplicates excluded, no intrabar high or interpolation.",
                "SAMPLED_PARTIAL and missing samples are censored, not failures; even COMPLETE means feed window elapsed, not guaranteed continuous coverage.",
                "Lane cohorts overlap; their counts are not independent and must not be summed.",
                "No production BUY, threshold changes, order placement or FROZEN model modifications."]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.db, args.ledger), sort_keys=True))
