"""Read-only SHADOW lead-time evaluation on real prospective scout snapshots.

Only sessions beginning 2026-10-12 are eligible: the first full market
session after the v0.4 shadow experiment was introduced. Replaying a
watch after the fact NEVER earns live-signal credit. No BUY or ASK claim.
"""
import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from radar.audit_leadtime_10m import evaluate, parse_ts
from radar.shadow_early_watch import screen

START_SESSION = "2026-10-12"
INDEPENDENT_LAG = timedelta(seconds=1)


def audit(db_path, ledger_path, start_session=START_SESSION):
    if start_session < START_SESSION:
        raise ValueError("Cannot backdate the SHADOW evaluation start")
    ledger = [json.loads(s) for s in Path(ledger_path).read_text().splitlines() if s.strip()]
    records = {}
    for row in ledger:
        if row["session"] < start_session:
            continue
        key = (row["session"], row["symbol"])
        if key in records:
            raise ValueError("Duplicate immutable first-seen key: " + repr(key))
        records[key] = row

    conn = sqlite3.connect("file:" + str(Path(db_path).resolve()) + "?mode=ro", uri=True)
    samples = defaultdict(list)
    sessions = set()
    try:
        for session, symbol, ts, pct in conn.execute(
            "SELECT session,symbol,retrieval_ts,change_pct FROM scout_history "
            "WHERE session >= ? ORDER BY session,symbol,retrieval_ts", (start_session,)
        ):
            sessions.add(session)
            t = parse_ts(ts)
            try:
                p = float(pct)
            except (TypeError, ValueError):
                continue
            if t is not None and math.isfinite(p) and p > -100:
                samples[(session, symbol)].append((t, p))
    finally:
        conn.close()

    latest_session = max(sessions) if sessions else None
    cases = []
    for (session, symbol), row in sorted(records.items()):
        seen = parse_ts(row.get("first_eligible_ts"))
        try:
            first_pct = float(row["first_change_pct"])
        except (KeyError, TypeError, ValueError):
            first_pct = None
        valid_first = (seen is not None and first_pct is not None
                       and math.isfinite(first_pct) and 0 <= first_pct < 10)
        series = samples[(session, symbol)]
        observations = [{"ts": t.isoformat(), "change_pct": p} for t, p in series]
        first = {"ts": row.get("first_eligible_ts"), "change_pct": first_pct}
        onset = evaluate(first, observations) if valid_first else {
            "status": "UNVERIFIABLE", "reason": "invalid_first_eligible_scout"
        }
        future = [(t, p) for t, p in series if valid_first and
                  t >= seen + INDEPENDENT_LAG]
        max_future = max((p for _, p in future), default=None)
        first30 = next((t for t, p in series if p >= 30), None)
        first50 = next((t for t, p in series if p >= 50), None)
        # This replay uses after-the-fact stored scout observations. It is
        # NOT a prospectively emitted SHADOW watch or an executable ASK.
        replay = screen(observations)
        cases.append({
            "session": session, "symbol": symbol,
            "first_eligible_scout_ts": row.get("first_eligible_ts"),
            "first_eligible_scout_pct": first_pct,
            "onset_status": onset["status"],
            "lead_minutes": onset.get("lead_minutes"),
            "observed_onset_ts": onset.get("acceleration_onset_ts"),
            "onset_reason": onset.get("reason"),
            "first_observed_30_ts": first30.isoformat() if first30 else None,
            "first_observed_50_ts": first50.isoformat() if first50 else None,
            "observed_30_after_scout": bool(first30 and seen and first30 >= seen + INDEPENDENT_LAG),
            "observed_50_after_scout": bool(first50 and seen and first50 >= seen + INDEPENDENT_LAG),
            "max_future_scout_pct": max_future,
            "future_snapshot_count": len(future),
            "session_complete_in_feed": bool(latest_session and session < latest_session),
            "censored": not bool(latest_session and session < latest_session),
            "replay_watch_ts": replay.get("first_watch_ts"),
            "replay_watch_pct": replay.get("first_watch_change_pct"),
            "replay_status": "OFFLINE_REPLAY_NO_LIVE_CREDIT",
            "ask_execution": "UNKNOWN_NO_EXECUTABLE_ASK",
        })

    # Denominator: observed scout-history +30/+50 names, NOT independent
    # market-wide movers. The latter requires a separate source and coverage.
    winners30 = {(s, symbol) for (s, symbol), series in samples.items()
                 if any(p >= 30 for _, p in series)}
    winners50 = {(s, symbol) for (s, symbol), series in samples.items()
                 if any(p >= 50 for _, p in series)}
    captured30 = sum(c["observed_30_after_scout"] for c in cases
                     if (c["session"], c["symbol"]) in winners30)
    captured50 = sum(c["observed_50_after_scout"] for c in cases
                     if (c["session"], c["symbol"]) in winners50)
    return {
        "status": "SHADOW_OFFLINE_PROSPECTIVE_SESSION_REPLAY_NOT_BUY",
        "start_session": start_session,
        "protocol": "first-scout vs first observed acceleration onset, not peak",
        "sampled_scout_universe": {
            "observed_30_symbol_sessions": len(winners30),
            "observed_50_symbol_sessions": len(winners50),
            "eligible_first_scout_before_30": captured30,
            "eligible_first_scout_before_50": captured50,
            "denominator_note": "SCOUT_HISTORY coverage only; NOT market-wide recall",
        },
        "cohort": {
            "first_eligible_scout_candidates": len(cases),
            "early_10m": sum(c["onset_status"] == "EARLY_10M" for c in cases),
            "late": sum(c["onset_status"] == "LATE" for c in cases),
            "missed": sum(c["onset_status"] == "MISSED" for c in cases),
            "unverifiable_onset": sum(c["onset_status"] == "UNVERIFIABLE" for c in cases),
            "observed_later_30": sum(c["observed_30_after_scout"] for c in cases),
            "observed_later_50": sum(c["observed_50_after_scout"] for c in cases),
            "censored_sessions": sum(c["censored"] for c in cases),
            "observed_without_later_30_censored_or_incomplete":
                sum(not c["observed_30_after_scout"] for c in cases),
        },
        "warnings": [
            "OFFLINE REPLAY ONLY: no SHADOW first-watch timestamp was emitted in real time; zero live detection credit.",
            "No +15% executable-entry result: FIRST_SCOUT_PRICE is not ASK, NBBO, fill or tradable P&L.",
            "Unobserved onset is UNKNOWN, not a confirmed negative; missing 1m cadence cannot be interpolated.",
            "Observed nonwinners are censored/possible decoys, not validated 7-day false positives.",
            "Full market winner recall, precision, false-positive rate and OOS are NOT VALIDATED.",
            "v0.3.3 FROZEN, live workflows, BUY and orders are untouched.",
        ],
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.db, args.ledger), indent=2, sort_keys=True))
