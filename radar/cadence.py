"""Bounded feedback for dispatch latency; never changes observation timestamps."""
import math
from datetime import datetime
from zoneinfo import ZoneInfo


def observation_window(now):
    """One operational window in exchange time; reject ambiguous naive clocks."""
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    local = now.astimezone(ZoneInfo('America/New_York'))
    return local.weekday() < 5 and 4 <= local.hour < 20


def dispatch_wait(starts, now, target=300, previous_compensation=0):
    if target <= 0:
        raise ValueError('positive cadence target required')
    correction = 0.0
    gap = None
    if len(starts) >= 2:
        latest, previous = (datetime.fromisoformat(s) for s in starts[:2])
        gap = (latest - previous).total_seconds()
        # Do not compensate for overnight gaps, inverted time, or an outage.
        same_session = latest.astimezone(ZoneInfo('America/New_York')).date() == previous.astimezone(ZoneInfo('America/New_York')).date()
        if same_session and 0 < gap <= 2 * target:
            correction = min(60, max(0, previous_compensation + gap - target))
    elapsed = (now - datetime.fromisoformat(starts[0])).total_seconds() if starts else target
    return {'wait_seconds': max(0, math.ceil(target - correction - elapsed)),
            'target_seconds': target, 'previous_gap_seconds': gap,
            'latency_compensation_seconds': correction,
            'guaranteed_cadence': False}
