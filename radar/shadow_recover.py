"""Read-only Alpaca IEX minute-bar follow-up for persisted SHADOW alerts."""
import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://data.alpaca.markets/v2/stocks/bars"

def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

def recover(tracked, fetch):
    outcomes = {}
    for symbol, item in sorted(tracked.items()):
        first = parse_ts(item["first_seen"])
        end = first + timedelta(minutes=240)
        try:
            rows = fetch(symbol, first, end)
        except Exception as exc:
            outcomes[symbol] = {"first_seen": item["first_seen"], "first_price": item["first_price"],
                                "max_bar_high_after": None, "max_pct_after": None,
                                "minute_bars_after": 0, "status": "DATA_GAP",
                                "reason": type(exc).__name__}
            continue
        # A one-minute bar can straddle the alert. Exclude its entire minute;
        # otherwise its high could have happened before first_seen.
        eligible = [(parse_ts(b["t"]), float(b["h"])) for b in rows
                    if parse_ts(b["t"]) >= first.replace(second=0, microsecond=0) + timedelta(minutes=1)
                    and parse_ts(b["t"]) <= end and float(b["h"]) > 0]
        if eligible:
            highest = max(eligible, key=lambda x: x[1])
            price = highest[1]
            outcomes[symbol] = {"first_seen": item["first_seen"], "first_price": item["first_price"],
                                "max_bar_high_after": price, "max_bar_high_ts": highest[0].isoformat(),
                                "max_pct_after": round((price / float(item["first_price"]) - 1) * 100, 4),
                                "minute_bars_after": len(eligible), "status": "OBSERVED",
                                "caveat": "IEX 1m OHLC bar highs; not guaranteed executable fills"}
        else:
            outcomes[symbol] = {"first_seen": item["first_seen"], "first_price": item["first_price"],
                                "max_bar_high_after": None, "max_pct_after": None,
                                "minute_bars_after": 0, "status": "DATA_GAP"}
    return outcomes

def alpaca_fetch(key, secret, symbol, start, end):
    bars, token = [], None
    while True:
        params = {"symbols": symbol, "timeframe": "1Min", "start": start.isoformat(),
                  "end": end.isoformat(), "feed": "iex", "limit": 10000}
        if token:
            params["page_token"] = token
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params),
              headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
        bars.extend(data.get("bars", {}).get(symbol, []))
        token = data.get("next_page_token")
        if not token:
            break
    return bars

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("DATA_GAP: Alpaca credentials unavailable")
    state = json.loads(Path(args.state).read_text())
    outcomes = recover(state.get("tracked", {}), lambda s, a, b: alpaca_fetch(key, secret, s, a, b))
    result = {"mode": "SHADOW_ONLY", "buy": False, "provider": "alpaca_iex_1min",
              "outcomes": outcomes, "observed": sum(v["status"] == "OBSERVED" for v in outcomes.values()),
              "data_gap": sum(v["status"] == "DATA_GAP" for v in outcomes.values())}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")

if __name__ == "__main__":
    main()
