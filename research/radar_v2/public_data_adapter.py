"""Public Yahoo Finance chart JSON adapter for *limited* research samples.

No credentials; no trades. Yahoo availability and historical depth vary.
This is NOT a licensed consolidated US market feed or 12-month intraday universe.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
def fetch(symbol, interval="1d", range_="1mo", timeout=20):
    if interval not in ("1d", "1h", "5m", "1m"):
        raise ValueError("unsupported interval")
    if range_ not in ("5d", "1mo", "3mo", "6mo", "1y"):
        raise ValueError("unsupported range")
    url = URL.format(symbol=urllib.parse.quote(symbol, safe="")) + "?" + urllib.parse.urlencode({
        "interval": interval, "range": range_, "includePrePost": "false"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 RadarV2-Research"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.load(response)
    if payload.get("chart", {}).get("error"):
        raise RuntimeError(str(payload["chart"]["error"]))
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if result is None:
        raise ValueError("empty provider response")
    ts = result.get("timestamp") or []
    indicators = result["indicators"]["quote"][0]
    rows = []
    for idx, stamp in enumerate(ts):
        row = {"symbol": symbol, "provider": "yahoo_chart_unofficial",
               "source_ts": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
               "interval": interval}
        for field in ("open", "high", "low", "close", "volume"):
            values = indicators.get(field) or []
            row[field] = values[idx] if idx < len(values) else None
        if row["close"] is not None:
            rows.append(row)
    return rows

def write_snapshot(symbol, interval, range_, output):
    rows = fetch(symbol, interval, range_)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
    return len(rows)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="AAPL")
    p.add_argument("--interval", default="1d")
    p.add_argument("--range", dest="range_", default="1mo")
    p.add_argument("--output", default="research/radar_v2/data/sample.jsonl")
    args = p.parse_args()
    print("downloaded_rows:", write_snapshot(args.symbol, args.interval, args.range_, args.output))
