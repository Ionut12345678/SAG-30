"""Research-only offline evaluation. No broker access or trading."""
from dataclasses import dataclass
from datetime import datetime, timezone

THRESHOLDS = (15, 20, 30, 50)

@dataclass(frozen=True)
class Event:
    symbol: str
    source_ts: datetime
    ingest_ts: datetime
    price: float
    prior_close: float
    volume: int | None
    provider: str

def utc(value):
    if value.tzinfo is None:
        raise ValueError("timestamps must have timezone")
    return value.astimezone(timezone.utc)

def evaluate(events, max_age_seconds=300):
    ordered = sorted(enumerate(events), key=lambda item: (utc(item[1].ingest_ts), item[0]))
    first, milestones, rejected, seen = {}, {}, {}, set()
    accepted_quotes = 0
    for _, e in ordered:
        src, ing = utc(e.source_ts), utc(e.ingest_ts)
        if e.price <= 0 or e.prior_close <= 0:
            reason = "invalid_price"
        else:
            key = (e.provider, e.symbol, src, e.price, e.volume)
            if key in seen:
                reason = "duplicate"
            else:
                seen.add(key)
                if src > ing:
                    reason = "future_source"
                elif (ing - src).total_seconds() > max_age_seconds:
                    reason = "stale"
                elif e.volume is None or e.volume <= 0:
                    reason = "invalid_volume"
                else:
                    reason = None
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        accepted_quotes += 1
        if e.symbol not in first:
            if 3 <= 100 * (e.price / e.prior_close - 1) <= 10:
                first[e.symbol] = e
            continue
        start = first[e.symbol]
        if src <= utc(start.ingest_ts) or ing <= utc(start.ingest_ts):
            reason = "not_after_first_seen"
        elif abs(e.prior_close - start.prior_close) > max(1e-8, start.prior_close * 1e-8):
            reason = "reference_changed"
        else:
            reason = None
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        for threshold in THRESHOLDS:
            if e.price >= start.prior_close * (1 + threshold / 100):
                milestones.setdefault((e.symbol, threshold), e)
    return {
        "discoveries": len(first),
        "discovered_symbols": sorted(first),
        "validated_milestone_counts": {
            str(t): sum((symbol, t) in milestones for symbol in first)
            for t in THRESHOLDS
        },
        "accepted_quotes": accepted_quotes,
        "rejections": rejected,
        "note": "Historical research only. Never add replay to prospective SHADOW totals."
    }
