"""Non-authoritative semantic evidence SHADOW metrics.

This module records prospective, directly measurable path statistics without
promoting or changing SAG-30 v0.3.3 FROZEN states. It is research telemetry for
a future versioned semantic specification.
"""
import json
from datetime import datetime
from statistics import median

def init(db):
    db.execute("""
    CREATE TABLE IF NOT EXISTS semantic_shadow(
      observation_id INTEGER PRIMARY KEY,
      recorded_ts TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """)

def _session(ts):
    return datetime.fromisoformat(ts).date().isoformat()

def _daily_volume(raw):
    try:
        payload=json.loads(raw)
        value=(payload.get('dailyBar') or {}).get('v')
        return float(value) if value is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

def build(db, observation_id, recorded_ts):
    """Record raw path metrics. No semantic gate is asserted."""
    init(db)
    row=db.execute(
        "SELECT symbol,retrieval_ts,source_ts,quality,price,change_pct,payload "
        "FROM observations WHERE id=?",(observation_id,)
    ).fetchone()
    if not row:
        raise ValueError("Unknown observation")
    symbol,retrieval_ts,source_ts,quality,price,change_pct,raw=row
    session=_session(retrieval_ts)

    prior=db.execute(
        "SELECT id,retrieval_ts,price,change_pct,payload FROM observations "
        "WHERE symbol=? AND id<? AND quality='OK' ORDER BY id DESC LIMIT 12",
        (symbol,observation_id)
    ).fetchall()
    same_session=[r for r in reversed(prior) if _session(r[1]) == session]

    previous=same_session[-1] if same_session else None
    prices=[float(r[2]) for r in same_session if r[2] is not None]
    pcts=[float(r[3]) for r in same_session if r[3] is not None]

    previous_price=float(previous[2]) if previous and previous[2] is not None else None
    previous_pct=float(previous[3]) if previous and previous[3] is not None else None
    price_delta=None if previous_price is None or price is None else float(price)-previous_price
    pct_delta=None if previous_pct is None or change_pct is None else float(change_pct)-previous_pct
    prior_high=max(prices) if prices else None
    new_observed_high=bool(prior_high is not None and price is not None and float(price) > prior_high)

    consecutive_positive=0
    if same_session and price is not None:
        seq=[float(r[2]) for r in same_session[-2:] if r[2] is not None] + [float(price)]
        if len(seq) >= 2 and seq[-1] > seq[-2]:
            consecutive_positive=1
            if len(seq) >= 3 and seq[-2] > seq[-3]:
                consecutive_positive=2

    observed_peak=max(prices+[float(price)]) if price is not None else (max(prices) if prices else None)
    peak_pct=max(pcts+[float(change_pct)]) if change_pct is not None else (max(pcts) if pcts else None)
    giveback_pp=None if peak_pct is None or change_pct is None else peak_pct-float(change_pct)

    current_volume=_daily_volume(raw)
    # Same-clock research samples from earlier sessions. We expose the raw sample
    # count and ratio but DO NOT call the baseline "valid" because v0.3.3 does not
    # define baseline construction or minimum sample size.
    current_clock=datetime.fromisoformat(retrieval_ts).strftime("%H:%M")
    hist=db.execute(
        "SELECT retrieval_ts,payload FROM observations "
        "WHERE symbol=? AND id<? AND quality='OK' ORDER BY id DESC LIMIT 300",
        (symbol,observation_id)
    ).fetchall()
    by_session={}
    for ts,payload in hist:
        if _session(ts) == session:
            continue
        if datetime.fromisoformat(ts).strftime("%H:%M") != current_clock:
            continue
        vol=_daily_volume(payload)
        if vol is not None:
            by_session.setdefault(_session(ts),vol)
    samples=list(by_session.values())
    baseline_median=median(samples) if samples else None
    observed_rvol=None
    if current_volume is not None and baseline_median not in (None,0):
        observed_rvol=current_volume/baseline_median

    payload={
      "version":"semantic-shadow-v1",
      "authoritative":False,
      "symbol":symbol,
      "source_ts":source_ts,
      "retrieval_ts":retrieval_ts,
      "quality":quality,
      "price":price,
      "change_pct":change_pct,
      "previous_price":previous_price,
      "previous_change_pct":previous_pct,
      "price_delta":price_delta,
      "change_delta_pp":pct_delta,
      "new_observed_high":new_observed_high,
      "consecutive_positive_intervals":consecutive_positive,
      "observed_peak_price":observed_peak,
      "observed_peak_change_pct":peak_pct,
      "giveback_from_observed_peak_pp":giveback_pp,
      "current_cumulative_volume":current_volume,
      "same_clock_volume_sample_count":len(samples),
      "same_clock_volume_median":baseline_median,
      "observed_same_clock_volume_ratio":observed_rvol,
      "frozen_activity_baseline_valid":False,
      "frozen_activity_baseline_reason":"SHADOW metric only; v0.3.3 does not define baseline construction/minimum sample size",
      "notes":[
        "No semantic gate is promoted by this payload.",
        "Metrics are prospective and tied to the exact observation."
      ]
    }
    db.execute(
        "INSERT OR REPLACE INTO semantic_shadow(observation_id,recorded_ts,payload) VALUES(?,?,?)",
        (observation_id,recorded_ts,json.dumps(payload,sort_keys=True,separators=(',',':')))
    )
    return payload
