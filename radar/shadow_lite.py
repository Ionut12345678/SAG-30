"""Standalone, audit-friendly SHADOW detector. Standard library only. No trading."""
import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://data.alpaca.markets/v2/stocks/snapshots"
STATE_VERSION = 1
HORIZON_MIN = 240
MAX_CANDIDATES = 3
BATCH_SIZE = 100


def timestamp(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def market_window(now):
    ny = now.astimezone(ZoneInfo("America/New_York"))
    return ny.weekday() < 5 and 4 <= ny.hour < 20


def symbols_from_csv(path):
    with open(path, newline="") as stream:
        return list(dict.fromkeys(row["symbol"].strip().upper() for row in csv.DictReader(stream)
                                  if row.get("symbol") and row["symbol"].strip()))


def fetch_snapshots(symbols, key, secret, feed="iex"):
    """Fail closed on a failed batch. Never label partial coverage complete."""
    result = {}
    for i in range(0, len(symbols), BATCH_SIZE):
        group = symbols[i:i + BATCH_SIZE]
        url = API + "?" + urllib.parse.urlencode({"symbols": ",".join(group), "feed": feed})
        request = urllib.request.Request(url, headers={
            "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json", "User-Agent": "sag30-shadow-lite/1"})
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("Snapshot response is not an object")
        result.update(payload)
    return result


def valid_price(symbol, snapshot, now, max_age_seconds=900):
    """Use timestamped trades only. Day high is NOT a post-alert high."""
    trade = snapshot.get("latestTrade") or {}
    daily = snapshot.get("dailyBar") or {}
    previous = snapshot.get("prevDailyBar") or {}
    ts = timestamp(trade.get("t"))
    price = trade.get("p")
    close = previous.get("c")
    if ts is None or ts > now or (now - ts).total_seconds() > max_age_seconds:
        return None
    if not isinstance(price, (int, float)) or not isinstance(close, (int, float)):
        return None
    if price <= 0 or close <= 0:
        return None
    # Daily bar timestamp can be missing on some feeds; never use its high as an outcome.
    return {"symbol": symbol, "price": price, "change_pct": round((price / close - 1) * 100, 4),
            "source_ts": ts.isoformat(), "source": "alpaca_snapshot_latestTrade",
            "feed": "iex", "previous_close": close}


def cycle(now, universe, snapshots, prior):
    """Immutable first_seen; outcomes require observations strictly AFTER detection."""
    state = dict(prior or {})
    if state.get("version") not in (None, STATE_VERSION):
        raise ValueError("Unsupported state version")
    tracked = dict(state.get("tracked") or {})
    events = list(state.get("events") or [])
    candidates, observed = [], {}
    for symbol in universe:
        snap = snapshots.get(symbol)
        if not isinstance(snap, dict):
            continue
        row = valid_price(symbol, snap, now)
        if row:
            observed[symbol] = row
            if 5 <= row["change_pct"] <= 10 and symbol not in tracked:
                candidates.append(row)
    candidates.sort(key=lambda row: (-row["change_pct"], row["symbol"]))
    selected = candidates[:MAX_CANDIDATES]
    new_events = []
    for row in selected:
        symbol = row["symbol"]
        # This is the actual cycle detection time, not an inferred earlier event.
        event = {"type": "FIRST_WATCH", "symbol": symbol, "first_seen": now.isoformat(),
                 "source_ts": row["source_ts"], "source": row["source"],
                 "feed": row["feed"], "price": row["price"],
                 "change_pct": row["change_pct"], "decision": "SHADOW_WATCH_NOT_BUY"}
        tracked[symbol] = {"first_seen": now.isoformat(), "first_price": row["price"],
                           "first_change_pct": row["change_pct"], "source_ts": row["source_ts"],
                           "max_observed_price_after": None, "max_observed_pct_after": None,
                           "milestones": [], "status": "ACTIVE"}
        new_events.append(event)
    for symbol, item in tracked.items():
        first = timestamp(item.get("first_seen"))
        if first is None:
            raise ValueError("Tracked symbol lacks valid first_seen")
        minutes = (now - first).total_seconds() / 60
        if minutes < 0:
            raise ValueError("State first_seen lies in future")
        if minutes > HORIZON_MIN:
            if item["status"] == "ACTIVE":
                item["status"] = "CENSORED_OR_WINDOW_COMPLETE"
            continue
        row = observed.get(symbol)
        if row is None or now <= first:
            continue
        # A snapshot whose source timestamp predates detection cannot be used.
        source_ts = timestamp(row["source_ts"])
        if source_ts is None or source_ts <= first:
            continue
        old = item.get("max_observed_price_after")
        if old is None or row["price"] > old:
            item["max_observed_price_after"] = row["price"]
            item["max_observed_pct_after"] = round((row["price"] / item["first_price"] - 1) * 100, 4)
        # +15/+20/+30/+50 are measured against previous close, only after detection.
        achieved = set(item.get("milestones") or [])
        for level in (15, 20, 30, 50):
            if row["change_pct"] >= level and level not in achieved:
                item["milestones"].append(level)
                new_events.append({"type": "POST_ALERT_MILESTONE", "symbol": symbol,
                                   "level_pct_vs_previous_close": level, "observed_at": now.isoformat(),
                                   "source_ts": row["source_ts"], "price": row["price"],
                                   "change_pct": row["change_pct"],
                                   "lead_minutes": round(minutes, 2),
                                   "decision": "SHADOW_NOT_BUY"})
    events.extend(new_events)
    # Keep evidence bounded without rewriting first_seen of tracked candidates.
    state.update(version=STATE_VERSION, tracked=tracked, events=events[-2000:],
                 last_cycle=now.isoformat())
    return state, {"generated_ts": now.isoformat(), "mode": "SHADOW_ONLY",
                   "universe_size": len(universe), "valid_fresh_snapshots": len(observed),
                   "new_watch": selected, "new_events": new_events,
                   "tracked_count": len(tracked), "max_candidates_per_cycle": MAX_CANDIDATES,
                   "horizon_minutes": HORIZON_MIN, "buy": False,
                   "caveats": ["No actual bid/ask or halt verification: UNKNOWN",
                               "Observed subsequent prices are not exchange intraday highs",
                               "Missing snapshots are censored, not negatives"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="config/universe.csv")
    parser.add_argument("--state", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    state_file = Path(args.state)
    prior = json.loads(state_file.read_text()) if state_file.exists() else {}
    report = {"generated_ts": now.isoformat(), "mode": "SHADOW_ONLY", "buy": False}
    if not market_window(now):
        report.update(status="OUTSIDE_WINDOW", new_events=[])
    else:
        key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            report.update(status="DATA_GAP", reason="ALPACA_CREDENTIALS_MISSING", new_events=[])
        else:
            try:
                universe = symbols_from_csv(args.universe)
                if not universe:
                    raise ValueError("Empty universe")
                snapshots = fetch_snapshots(universe, key, secret)
                state, detail = cycle(now, universe, snapshots, prior)
                report.update(detail)
                report["status"] = "OBSERVED" if detail["valid_fresh_snapshots"] else "DATA_GAP"
                if detail["valid_fresh_snapshots"]:
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
                else:
                    report["reason"] = "NO_FRESH_SNAPSHOTS"
            except Exception as exc:
                report.update(status="DATA_GAP", reason=type(exc).__name__, new_events=[])
                print(f"SHADOW_LITE_DATA_GAP: {type(exc).__name__}: {exc}", file=sys.stderr)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "new_events"}, sort_keys=True))
    return 0 if report["status"] in ("OUTSIDE_WINDOW", "OBSERVED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
