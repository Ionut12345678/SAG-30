"""Closed-session minute-bar replay helpers, SHADOW only.

A historical minute CLOSE becomes observable at bar END; a target HIGH can
occur anywhere within the bar, so its bar START is used conservatively.
These data cannot prove execution, live detection, or a BUY.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def parse_ts(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("naive timestamp")
    return stamp.astimezone(timezone.utc)


def match_cases(winners, negatives, dates, cap=5):
    win, neg = defaultdict(list), defaultdict(list)
    for x in winners:
        win[x["date"]].append(x)
    for x in negatives:
        neg[x["date"]].append(x)
    rows, shortage = [], {}
    for day in dates:
        w = sorted(win[day], key=lambda x: (-x["daily_high_pct"], x["symbol"]))[:cap]
        n = sorted(neg[day], key=lambda x: (-x["daily_high_pct"], x["symbol"]))[:len(w)]
        if len(n) < len(w):
            shortage[day] = len(w) - len(n)
        rows += [{**x, "label": "winner"} for x in w]
        rows += [{**x, "label": "hard_negative"} for x in n]
    return rows, shortage


def replay(case, sip, iex):
    prev = float(case["prev_close"])
    first_close = {n: None for n in (3, 5, 10, 15, 20)}
    first_high = {n: None for n in (30, 50)}
    sip_minutes, iex_minutes = set(), set()
    prior, streak, momentum = None, 0, None
    for b in sorted(sip, key=lambda x: x["t"]):
        try:
            start = parse_ts(b["t"])
            if start.astimezone(ET).date().isoformat() != case["date"]:
                continue
            close, high = float(b["c"]), float(b["h"])
            if min(close, high) <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        sip_minutes.add(start.isoformat())
        cp, hp = 100 * (close / prev - 1), 100 * (high / prev - 1)
        for target in first_high:
            if first_high[target] is None and hp >= target:
                first_high[target] = start
        observed = start + timedelta(minutes=1)
        for level in first_close:
            if first_close[level] is None and cp >= level:
                first_close[level] = observed
        if prior:
            gap = (start - prior[0]).total_seconds() / 60
            streak = streak + 1 if 0 < gap <= 5 and close > prior[1] and float(b.get("v") or 0) > 0 else 0
        if momentum is None and streak >= 2 and 3 <= cp < 10 and first_high[30] is None:
            momentum = observed
        prior = start, close
    for b in iex:
        try:
            t = parse_ts(b["t"])
            if t.astimezone(ET).date().isoformat() == case["date"]:
                iex_minutes.add(t.isoformat())
        except (KeyError, TypeError, ValueError):
            continue
    def lead(observed, target):
        return (target - observed).total_seconds() / 60 if observed and target and observed < target else None
    lead5 = lead(first_close[5], first_high[30])
    lead_m = lead(momentum, first_high[30])
    return {**case, "sip_minutes": len(sip_minutes), "iex_minutes": len(iex_minutes),
            "iex_overlap_ratio": round(len(sip_minutes & iex_minutes) / len(sip_minutes), 4) if sip_minutes else None,
            "first_close_utc": {str(k): v.isoformat() if v else None for k, v in first_close.items()},
            "first_target_high_bar_start_utc": {str(k): v.isoformat() if v else None for k, v in first_high.items()},
            "first_momentum_utc": momentum.isoformat() if momentum else None,
            "lead5_to30_minutes": lead5, "momentum_lead30_minutes": lead_m,
            "early5_before30": lead5 is not None, "momentum_before30": lead_m is not None}


def metrics(rows):
    n = len(rows)
    ratios = [x["iex_overlap_ratio"] for x in rows if x["iex_overlap_ratio"] is not None]
    leads = [x["lead5_to30_minutes"] for x in rows if x["lead5_to30_minutes"] is not None]
    return {"cases": n, "with_sip_bars": sum(x["sip_minutes"] > 0 for x in rows),
            "early5_before30": sum(x["early5_before30"] for x in rows),
            "momentum_before30": sum(x["momentum_before30"] for x in rows),
            "early5_rate": sum(x["early5_before30"] for x in rows) / n if n else None,
            "momentum_rate": sum(x["momentum_before30"] for x in rows) / n if n else None,
            "median_lead5_minutes": median(leads) if leads else None,
            "median_iex_overlap": median(ratios) if ratios else None}
