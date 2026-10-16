"""Read-only T+1/T+2/T+5 session high follow-up from Alpaca daily bars."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from radar.shadow_recover import parse_ts

NY = ZoneInfo("America/New_York")
TARGETS = (1, 2, 5)


def evaluate(tracked, fetch, now):
    results = {}
    for symbol, item in sorted(tracked.items()):
        first = parse_ts(item["first_seen"])
        first_day = first.astimezone(NY).date()
        price = float(item["first_price"])
        record = {"first_seen": item["first_seen"], "first_price": price,
                  "mode": "SHADOW_ONLY", "buy": False}
        try:
            bars = fetch(symbol, first, now)
            sessions = {}
            for bar in bars:
                ts = parse_ts(bar["t"])
                day = ts.astimezone(NY).date()
                high = float(bar["h"])
                if day > first_day and math.isfinite(high) and high > 0:
                    sessions[day] = max(high, sessions.get(day, 0))
            days = sorted(sessions)
            # Fail closed on missing weekday bars. Holidays can cause false gaps,
            # but never a false validated T+n session.
            expected = []
            cursor = first_day + dt.timedelta(days=1)
            while cursor <= now.astimezone(NY).date():
                if cursor.weekday() < 5:
                    expected.append(cursor)
                cursor += dt.timedelta(days=1)
            for n in TARGETS:
                key = f"T+{n}"
                if len(expected) >= n and all(day in sessions for day in expected[:n]):
                    day = expected[n - 1]
                    high = sessions[day]
                    record[key] = {"status": "OBSERVED", "session": day.isoformat(),
                                   "session_high": high,
                                   "max_pct": round((high / price - 1) * 100, 4)}
                else:
                    record[key] = {"status": "NOT_MEASURED", "reason": "INSUFFICIENT_SESSIONS_OR_FEED_GAP_OR_HOLIDAY"}
        except Exception as exc:
            for n in TARGETS:
                record[f"T+{n}"] = {"status": "DATA_GAP", "reason": type(exc).__name__}
        results[symbol] = record
    return {"provider": "alpaca_iex_1day", "mode": "SHADOW_ONLY", "buy": False,
            "outcomes": results, "caveat": "Observed IEX session highs, not executable prices; missing feed sessions may shift T+n."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("DATA_GAP: Alpaca credentials unavailable")
    state = json.loads(Path(args.state).read_text())
    now = dt.datetime.now(dt.timezone.utc)
    # Reuse authenticated Alpaca API retrieval; request daily timeframe explicitly.
    import urllib.parse
    import urllib.request
    def fetch(symbol, first, end):
        bars, token = [], None
        while True:
            params = {"symbols": symbol, "timeframe": "1Day", "start": first.isoformat(),
                      "end": end.isoformat(), "feed": "iex", "limit": 10000}
            if token:
                params["page_token"] = token
            req = urllib.request.Request("https://data.alpaca.markets/v2/stocks/bars?" +
                urllib.parse.urlencode(params), headers={
                "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.load(response)
            bars.extend(payload.get("bars", {}).get(symbol, []))
            token = payload.get("next_page_token")
            if not token:
                break
        return bars
    result = evaluate(state.get("tracked", {}), fetch, now)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
