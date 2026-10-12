"""Retrospective SIP/IEX coverage diagnostics; SHADOW only, never BUY.

A minute bar is timestamped at its *start*. Coverage measures presence, not
quote accuracy or live tradeability. Inputs must refer to the same session.
"""
from datetime import timedelta
from statistics import median
from research.historical_replay_core import parse_ts


def coverage_audit(sip_bars, iex_bars, *, expected_minutes=None):
    """Compare minute-bar presence and report gaps without imputing prices.

    expected_minutes is an optional iterable of timezone-aware ISO timestamps
    for the intended session window; omitted means coverage denominator unknown.
    """
    def indexed(bars):
        result = {}
        for bar in bars:
            try:
                stamp = parse_ts(bar["t"])
                if float(bar["c"]) <= 0 or float(bar["h"]) <= 0:
                    continue
                result[stamp] = bar
            except (KeyError, ValueError, TypeError):
                continue
        return result

    sip, iex = indexed(sip_bars), indexed(iex_bars)
    both = sorted(set(sip) & set(iex))
    divergences = []
    for t in both:
        a, b = float(sip[t]["c"]), float(iex[t]["c"])
        if a > 0:
            divergences.append(abs(b / a - 1) * 100)
    expected = None if expected_minutes is None else {parse_ts(t) for t in expected_minutes}
    if expected is not None and not expected:
        raise ValueError("expected_minutes cannot be empty")
    def gaps(times):
        ordered = sorted(times)
        return sum(max(0, int((b-a).total_seconds() // 60)-1) for a,b in zip(ordered,ordered[1:]))
    return {
        "sip_bars": len(sip), "iex_bars": len(iex),
        "overlap_bars": len(both),
        "iex_vs_sip_presence_ratio": len(both)/len(sip) if sip else None,
        "sip_internal_missing_minutes": gaps(sip),
        "iex_internal_missing_minutes": gaps(iex),
        "sip_expected_coverage": len(set(sip)&expected)/len(expected) if expected is not None else None,
        "iex_expected_coverage": len(set(iex)&expected)/len(expected) if expected is not None else None,
        "median_close_divergence_pct": median(divergences) if divergences else None,
        "max_close_divergence_pct": max(divergences) if divergences else None,
        "mode": "RETROSPECTIVE_SHADOW_NOT_LIVE",
    }
