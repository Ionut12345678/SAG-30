"""SHADOW-only lead-time evaluation against observed acceleration windows.

The first SCOUT and first WATCH are distinct immutable prospective events.
Onset is an ex-post evaluation convention, never an input to a live signal.
No BUY, no FROZEN changes, and no credit for sparse/same-cycle evidence.
"""
import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIN_LEAD = timedelta(minutes=10)
MAX_GAP = timedelta(minutes=6)
ACCELERATION_WINDOW = timedelta(minutes=10)
ACCELERATION_GAIN_PCT = 20.0


def parse_ts(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def _event(event, prefix):
    if not isinstance(event, dict):
        return None, f"missing_{prefix}"
    ts = parse_ts(event.get("ts"))
    try:
        pct = float(event["change_pct"])
    except (ValueError, TypeError, KeyError):
        return None, f"missing_{prefix}_price"
    if ts is None or not math.isfinite(pct) or pct <= -100:
        return None, f"invalid_{prefix}"
    return (ts, pct), None


def evaluate(first_seen, observations, first_watch=None):
    """Evaluate an immutable SCOUT and WATCH against future observed samples.

    Inputs: first_seen/first_watch {ts, change_pct}, observations list of
    {ts, change_pct} from comparable, source-timestamped snapshots.
    EARLY_10M requires >=10m WATCH-to-observed-onset lead and <=6m gaps
    from WATCH through onset. An UNKNOWN is never counted as a decoy.
    """
    scout, error = _event(first_seen, "first_scout")
    if error:
        return {"status": "UNVERIFIABLE", "reason": error}
    watch, error = _event(first_watch, "first_watch")
    if error:
        return {"status": "UNVERIFIABLE", "reason": error}
    scout_ts, _ = scout
    watch_ts, _ = watch
    if watch_ts < scout_ts:
        return {"status": "UNVERIFIABLE", "reason": "watch_before_scout"}

    clean = []
    for row in observations:
        event, error = _event(row, "observation")
        if not error:
            clean.append(event)
    clean.sort()
    # Two different prices at the same timestamp are not ordered observations.
    if any(a[0] == b[0] and a[1] != b[1] for a, b in zip(clean, clean[1:])):
        return {"status": "UNVERIFIABLE", "reason": "conflicting_same_timestamp"}
    clean = [row for i, row in enumerate(clean) if i == 0 or row != clean[i - 1]]

    onset = None
    for i, (start, p0) in enumerate(clean):
        for j in range(i + 1, len(clean)):
            end, p1 = clean[j]
            elapsed = end - start
            if elapsed > ACCELERATION_WINDOW:
                break
            if elapsed < timedelta(seconds=1):
                continue
            if any(b[0] - a[0] > MAX_GAP for a, b in zip(clean[i:j], clean[i + 1:j + 1])):
                continue
            relative = 100 * ((100 + p1) / (100 + p0) - 1)
            if relative >= ACCELERATION_GAIN_PCT:
                onset = start
                break
        if onset is not None:
            break
    if onset is None:
        return {"status": "UNVERIFIABLE", "reason": "no_observed_acceleration_onset"}

    delta = onset - watch_ts
    if abs(delta.total_seconds()) < 1:
        return {"status": "UNVERIFIABLE", "reason": "same_cycle_watch_onset"}
    if delta > timedelta(0):
        # Require continuous source observations after the WATCH. An empty
        # interval cannot prove an early warning, even if a later jump occurs.
        stamps = [watch_ts] + [t for t, _ in clean if watch_ts < t <= onset]
        if stamps[-1] != onset or any(b - a > MAX_GAP for a, b in zip(stamps, stamps[1:])):
            return {"status": "UNVERIFIABLE", "reason": "coverage_gap_watch_to_onset"}

    lead = delta.total_seconds() / 60
    status = "EARLY_10M" if delta >= MIN_LEAD else "LATE" if delta > timedelta(0) else "MISSED"
    return {
        "status": status,
        "lead_minutes": round(lead, 3),
        "scout_lead_minutes": round((onset - scout_ts).total_seconds() / 60, 3),
        "first_scout_ts": scout_ts.isoformat(),
        "first_watch_ts": watch_ts.isoformat(),
        "acceleration_onset_ts": onset.isoformat(),
        "onset_definition": "first observed start of >=20% price-relative rise within <=10m; max 6m adjacent gaps",
        "warning": "SHADOW evaluation only; observed onset is not the physical start or an executable entry.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON list of {symbol,first_seen,first_watch,observations}")
    args = parser.parse_args()
    rows = json.loads(Path(args.input).read_text())
    result = [
        {"symbol": r["symbol"], **evaluate(r.get("first_seen"), r.get("observations", []), r.get("first_watch"))}
        for r in rows
    ]
    print(json.dumps({"status": "SHADOW_RESEARCH_ONLY_NOT_BUY", "cases": result}, indent=2))


if __name__ == "__main__":
    main()
