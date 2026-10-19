"""Fail-closed guard for independently timestamped Radar Nou observations.

Screen captures and retrieval timestamps are never quote timestamps.
No trading or Alpaca integrations.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LEVELS = (15, 20, 30, 50)

def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None

def validate(observation, now, max_age_seconds=120):
    """Return (eligible, reason). Requires an actual source quote timestamp."""
    if not isinstance(observation, dict):
        return False, "BAD_OBSERVATION"
    if observation.get("source_timestamp_verified_by_exchange") is not True:
        return False, "UNVERIFIED_SOURCE"
    if observation.get("source_kind") in ("screen_capture", "screener_snapshot"):
        return False, "SNAPSHOT_NOT_TRADE"
    dt = parse_time(observation.get("source_ts_utc"))
    if dt is None:
        return False, "MISSING_QUOTE_TIMESTAMP"
    now = now.astimezone(timezone.utc)
    age = (now - dt).total_seconds()
    if age < -5:
        return False, "FUTURE_QUOTE"
    if age > max_age_seconds:
        return False, "STALE_QUOTE"
    if dt.astimezone(ZoneInfo("America/New_York")).date() != now.astimezone(ZoneInfo("America/New_York")).date():
        return False, "WRONG_MARKET_DATE"
    try:
        pct = float(observation["pct_vs_previous_close"])
    except (ValueError, TypeError, KeyError):
        return False, "BAD_PERCENT"
    if not (-100 <= pct <= 100000):
        return False, "BAD_PERCENT"
    return True, "VALID"

def new_thresholds(state, symbol, observation, now):
    """Only new, verified quote prints may advance thresholds."""
    eligible, reason = validate(observation, now)
    if not eligible:
        return [], reason
    if symbol not in state:
        return [], "NO_BASELINE"
    baseline = state[symbol]
    if not baseline.get("baseline_verified"):
        return [], "UNVERIFIED_BASELINE"
    prior_ts = parse_time(baseline.get("last_accepted_source_ts_utc")) or parse_time(baseline.get("baseline_source_ts_utc"))
    current_ts = parse_time(observation["source_ts_utc"])
    if prior_ts is None or current_ts <= prior_ts:
        return [], "REPLAYED_OR_OUT_OF_ORDER"
    if baseline.get("baseline_source_ts_utc") and current_ts <= parse_time(baseline["baseline_source_ts_utc"]):
        return [], "NOT_LATER_THAN_BASELINE"
    pct = float(observation["pct_vs_previous_close"])
    already = set(baseline.get("confirmed_thresholds", []))
    new = [level for level in LEVELS if pct >= level and level not in already]
    baseline["last_accepted_source_ts_utc"] = observation["source_ts_utc"]
    baseline["confirmed_thresholds"] = sorted(already.union(new))
    return new, "ACCEPTED"
