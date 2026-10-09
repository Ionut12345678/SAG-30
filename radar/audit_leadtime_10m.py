"""SHADOW-only evaluation of detection lead time to a predeclared acceleration onset.

Retrospective onset uses future samples for evaluation ONLY, never as a signal.
Missing/irregular cadence is not interpolated. No BUY, no FROZEN changes.
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

def evaluate(first_seen, observations):
    """Input: first_seen {ts,change_pct}; observations chronological {ts,change_pct}.

    Onset = start of first <=10m consecutive, sufficiently covered sample pair
    with >=20% price-relative acceleration. This is an evaluation convention,
    NOT evidence of the true physical onset between samples.
    """
    entry_ts = parse_ts(first_seen.get("ts"))
    try:
        entry_pct = float(first_seen["change_pct"])
    except (ValueError, TypeError, KeyError):
        return {"status": "UNVERIFIABLE", "reason": "missing_first_price"}
    if entry_ts is None or not math.isfinite(entry_pct) or entry_pct <= -100:
        return {"status": "UNVERIFIABLE", "reason": "invalid_first_detection"}
    clean = []
    for row in observations:
        t = parse_ts(row.get("ts"))
        try:
            pct = float(row["change_pct"])
        except (ValueError, TypeError, KeyError):
            continue
        if t and math.isfinite(pct) and pct > -100:
            clean.append((t, pct))
    clean.sort()
    onset = None
    for i in range(len(clean)):
        start, p0 = clean[i]
        for end, p1 in clean[i+1:]:
            elapsed = end-start
            if elapsed > ACCELERATION_WINDOW:
                break
            if elapsed < timedelta(seconds=1):
                continue
            # Reject missing intermediate coverage and delayed 10m jump.
            segment = clean[i:clean.index((end,p1))+1]
            if any(b[0]-a[0] > MAX_GAP for a,b in zip(segment, segment[1:])):
                continue
            relative = 100*((100+p1)/(100+p0)-1)
            if relative >= ACCELERATION_GAIN_PCT:
                onset = start
                break
        if onset:
            break
    if onset is None:
        return {"status": "UNVERIFIABLE", "reason": "no_observed_acceleration_onset"}
    lead = (onset-entry_ts).total_seconds()/60
    status = "EARLY_10M" if lead >= 10 else "LATE" if lead >= 0 else "MISSED"
    return {"status":status, "lead_minutes":round(lead,3),
            "first_detection_ts":entry_ts.isoformat(),
            "acceleration_onset_ts":onset.isoformat(),
            "onset_definition":"first observed start of >=20% relative change within <=10m; max 6m adjacent gaps"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True,help="JSON list of {symbol,first_seen,observations}")
    args=p.parse_args()
    rows=json.loads(Path(args.input).read_text())
    result=[{"symbol":r["symbol"],**evaluate(r["first_seen"],r["observations"])} for r in rows]
    print(json.dumps({"status":"SHADOW_RESEARCH_ONLY_NOT_BUY","cases":result},indent=2))

if __name__=="__main__":
    main()
