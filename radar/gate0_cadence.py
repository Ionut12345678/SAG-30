"""Auditable 5-minute US regular-session schedule slots; no trading."""
import datetime as dt
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def eligible_slots(start, end):
    """UTC timestamps for NY weekdays 09:35..15:55, DST aware; end exclusive."""
    day = start.astimezone(NY).date() - dt.timedelta(days=1)
    last = end.astimezone(NY).date() + dt.timedelta(days=1)
    slots = []
    while day <= last:
        if day.weekday() < 5:
            local = dt.datetime.combine(day, dt.time(9, 35), tzinfo=NY)
            close = dt.datetime.combine(day, dt.time(16), tzinfo=NY)
            while local < close:
                stamp = local.astimezone(UTC)
                if start <= stamp < end:
                    slots.append(stamp)
                local += dt.timedelta(minutes=5)
        day += dt.timedelta(days=1)
    return slots


def audit(runs, start, end, grace_minutes=5):
    """Match at most one scheduled/manual run to each slot; delayed runs are gaps."""
    slots = eligible_slots(start, end)
    valid = []
    for run in runs:
        if run.get("event") not in ("schedule", "workflow_dispatch"):
            continue
        try:
            stamp = dt.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if start <= stamp < end:
            valid.append((stamp, run))
    valid.sort(key=lambda pair: pair[0])
    used = set()
    matched = []
    for slot in slots:
        candidates = [(abs((stamp - slot).total_seconds()), i) for i, (stamp, _) in enumerate(valid)
                      if i not in used and 0 <= (stamp - slot).total_seconds() <= grace_minutes * 60]
        if candidates:
            _, idx = min(candidates)
            used.add(idx)
            matched.append({"slot": slot.isoformat(), "run_id": valid[idx][1].get("id"),
                            "conclusion": valid[idx][1].get("conclusion")})
    return {"expected_slots": len(slots), "matched_slots": len(matched),
            "missing_slots": len(slots) - len(matched),
            "coverage_pct": round(100 * len(matched) / len(slots), 2) if slots else None,
            "matched": matched,
            "caveat": "Weekdays only: exchange holidays and early closes must be excluded before final PASS."}
