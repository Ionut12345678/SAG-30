"""Research-only causal event detector. Python standard library; never places orders."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

UTC = timezone.utc

@dataclass(frozen=True)
class Quote:
    symbol: str
    provider: str
    source_ts: datetime
    ingest_ts: datetime
    price: float
    previous_regular_close: float
    volume: Optional[int] = None

@dataclass(frozen=True)
class Observation:
    quote: Quote
    first_seen: datetime
    pct_from_close: float
    validated: bool
    rejection_reason: Optional[str]

def _utc(dt):
    if dt.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")
    return dt.astimezone(UTC)

class CausalRadar:
    def __init__(self, max_age=timedelta(minutes=5)):
        self.max_age = max_age
        self.seen_quotes = set()
        self.first_seen_by_symbol = {}
        self.observations = []
        self.milestones = {}
        self.thresholds = (15, 20, 30, 50)

    def ingest(self, quote: Quote):
        src, ing = _utc(quote.source_ts), _utc(quote.ingest_ts)
        if quote.price <= 0 or quote.previous_regular_close <= 0:
            raise ValueError("Prices and reference must be positive")
        if quote.volume is not None and quote.volume < 0:
            raise ValueError("Volume cannot be negative")
        key = (quote.provider, quote.symbol, src, quote.price, quote.volume)
        if key in self.seen_quotes:
            return None  # idempotent, not a new discovery
        self.seen_quotes.add(key)
        pct = 100 * (quote.price / quote.previous_regular_close - 1)
        reason = None
        if src > ing:
            reason = "future_source_timestamp"
        elif ing - src > self.max_age:
            reason = "stale_quote"
        elif quote.volume is None:
            reason = "missing_volume"
        elif quote.volume == 0:
            reason = "zero_volume"
        elif not 3 <= pct <= 10:
            reason = "outside_discovery_band"
        # Record all observations, including rejected ones, for an auditable trail.
        validated = reason is None
        obs = Observation(quote, ing, pct, validated, reason)
        self.observations.append(obs)
        if validated and quote.symbol not in self.first_seen_by_symbol:
            self.first_seen_by_symbol[quote.symbol] = obs
        # Subsequent milestones require a later *source* timestamp than initial
        # observation AND a later ingestion timestamp. A previously recorded
        # intrabar high can never become a post-discovery milestone.
        first = self.first_seen_by_symbol.get(quote.symbol)
        if first and first is not obs and src > _utc(first.quote.source_ts) and ing > first.first_seen and src > first.first_seen and quote.volume is not None and quote.volume > 0 and reason not in ("future_source_timestamp", "stale_quote"):
            baseline = first.quote.previous_regular_close
            for threshold in self.thresholds:
                if quote.price >= baseline * (1 + threshold / 100):
                    self.milestones.setdefault((quote.symbol, threshold), obs)
        return obs
