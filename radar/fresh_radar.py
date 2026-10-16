"""SAG-30 Fresh Radar: isolated observational detector, never trades."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from radar.shadow_lite import fetch_snapshots, market_window, symbols_from_csv, timestamp, valid_price

MAX_AGE_SECONDS = 120
MAX_WATCHES = 5
HORIZON_SECONDS = 4 * 60 * 60
MIN_COVERAGE = 0.8
THRESHOLDS = (15, 20, 30, 50)


def observe(now, symbols, snapshots, previous=None):
    state = json.loads(json.dumps(previous or {"version": 1, "tracked": {}, "events": []}))
    if state.get("version") != 1:
        raise ValueError("Unsupported state version")
    tracked = state.setdefault("tracked", {})
    events = state.setdefault("events", [])
    fresh = {}
    candidates = []
    age_values = []
    for symbol in symbols:
        snap = snapshots.get(symbol)
        if not isinstance(snap, dict):
            continue
        row = valid_price(symbol, snap, now)
        if row is None:
            continue
        age = (now - timestamp(row["source_ts"])).total_seconds()
        age_values.append(age)
        fresh[symbol] = row
        if 5 <= row["change_pct"] <= 10 and symbol not in tracked and age <= MAX_AGE_SECONDS:
            candidates.append((row["change_pct"], symbol, row, age))
    candidates.sort(key=lambda r: (-r[0], r[1]))
    new_events = []
    for _, symbol, row, age in candidates[:MAX_WATCHES]:
        item = {
            "symbol": symbol, "first_seen": now.isoformat(), "source_ts": row["source_ts"],
            "first_price": row["price"], "first_change_pct": row["change_pct"],
            "previous_close": row["previous_close"], "source_age_seconds": round(age, 2),
            "last_observation_ts": row["source_ts"], "max_post_price": None,
            "max_gain_from_entry_pct": None, "milestones": [], "status": "ACTIVE",
        }
        tracked[symbol] = item
        new_events.append({"type": "FIRST_WATCH", **item})
    # Post-alert evidence only from genuinely later market data. Never substitute day's high.
    for symbol, item in tracked.items():
        first = timestamp(item["first_seen"])
        if (now - first).total_seconds() > HORIZON_SECONDS:
            if item["status"] == "ACTIVE":
                item["status"] = "WINDOW_COMPLETE"
            continue
        row = fresh.get(symbol)
        if row is None:
            continue
        source = timestamp(row["source_ts"])
        if source <= first or source <= timestamp(item["last_observation_ts"]):
            continue
        item["last_observation_ts"] = row["source_ts"]
        item["max_post_price"] = max(item["max_post_price"] or 0, row["price"])
        item["max_gain_from_entry_pct"] = round(100 * (item["max_post_price"] / item["first_price"] - 1), 4)
        for threshold in THRESHOLDS:
            if row["change_pct"] >= threshold and threshold not in item["milestones"]:
                item["milestones"].append(threshold)
                new_events.append({
                    "type": "POST_ALERT_MILESTONE", "symbol": symbol,
                    "level_vs_previous_close": threshold, "price": row["price"],
                    "source_ts": row["source_ts"], "observed_at": now.isoformat(),
                    "gain_from_entry_pct": round(100 * (row["price"] / item["first_price"] - 1), 4),
                })
    events.extend(new_events)
    state["events"] = events[-5000:]
    state["last_cycle"] = now.isoformat()
    coverage = len(fresh) / len(symbols) if symbols else 0
    status = "DATA_GAP" if not fresh else ("OBSERVED" if coverage >= MIN_COVERAGE else "PARTIAL_OBSERVED")
    report = {
        "status": status, "observed_at": now.isoformat(), "universe": len(symbols),
        "fresh_snapshots": len(fresh), "coverage": round(coverage, 6),
        "fresh_source_age_le_120s": sum(a <= MAX_AGE_SECONDS for a in age_values),
        "new_watches": len([e for e in new_events if e["type"] == "FIRST_WATCH"]),
        "new_events": new_events, "tracked": len(tracked),
        "mode": "SHADOW_ONLY", "buy": False,
        "caveats": ["IEX-only, not consolidated", "No bid-ask, halt or fill verification",
                    "Milestones only from post-detection timestamped trades",
                    "Missing observations are unknown, not negative outcomes"],
    }
    return state, report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--state", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--universe", default="config/universe.csv")
    args = p.parse_args()
    now = datetime.now(timezone.utc)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    state_file = Path(args.state)
    prior = json.loads(state_file.read_text())
    report = {"observed_at": now.isoformat(), "mode": "SHADOW_ONLY", "buy": False}
    if not market_window(now):
        report["status"] = "OUTSIDE_WINDOW"
    elif not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_SECRET_KEY"):
        report.update(status="DATA_GAP", reason="ALPACA_CREDENTIALS_MISSING")
    else:
        try:
            symbols = symbols_from_csv(args.universe)
            if not symbols:
                raise ValueError("Empty universe")
            snapshots = fetch_snapshots(symbols, os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
            state, report = observe(now, symbols, snapshots, prior)
            if report["status"] != "DATA_GAP":
                state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        except Exception as exc:
            report.update(status="DATA_GAP", reason=type(exc).__name__)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "new_events"}, sort_keys=True))
    return 0 if report["status"] in ("OUTSIDE_WINDOW", "OBSERVED", "PARTIAL_OBSERVED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
