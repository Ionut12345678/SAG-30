"""Experimental Yahoo daily OHLC loader; no credentials, no trading integration."""
import argparse
import csv
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

def fetch(symbol, period="5y"):
    if not symbol.isascii() or not symbol.replace("-", "").replace(".", "").isalnum() or len(symbol) > 16:
        raise ValueError("Invalid ticker")
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" +
           urllib.parse.quote(symbol.upper(), safe="") +
           "?" + urllib.parse.urlencode({"range": period, "interval": "1d", "events": "div,splits"}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Radar100-research",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(3_000_000)
    payload = json.loads(raw)
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise ValueError(f"{symbol}: Yahoo response error: {chart.get('error')}")
    data = chart["result"][0]
    if data["meta"].get("currency") != "USD":
        raise ValueError(f"{symbol}: expected USD pricing")
    times = data.get("timestamp", [])
    q = data["indicators"]["quote"][0]
    adj = data["indicators"].get("adjclose", [{}])[0].get("adjclose")
    if not adj or len(adj) != len(times):
        raise ValueError(f"{symbol}: adjusted close unavailable, cannot ensure split consistency")
    rows = []
    for i, timestamp in enumerate(times):
        values = [q.get(k, [])[i] for k in ("open","high","low","close")]
        if any(v is None or not math.isfinite(v) or v <= 0 for v in values) or adj[i] is None:
            continue
        ratio = adj[i] / values[3]
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("Invalid adjustment factor")
        o,h,l,c = [v * ratio for v in values]
        if l > min(o,c) or h < max(o,c,l):
            raise ValueError("Invalid OHLC")
        rows.append({"symbol": symbol.upper(), "date": datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(),
                     "open": f"{o:.8f}", "high": f"{h:.8f}", "low": f"{l:.8f}", "close": f"{c:.8f}",
                     "volume": str(q["volume"][i] or 0)})
    rows.sort(key=lambda x:x["date"])
    if len(rows) < 600 or len({r["date"] for r in rows}) != len(rows):
        raise ValueError(f"{symbol}: insufficient or duplicated daily bars: {len(rows)}")
    return rows

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--range", default="5y", choices=["2y", "5y", "10y"])
    args = parser.parse_args()
    rows = []
    for sym in args.symbols:
        rows += fetch(sym, args.range)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix+".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol","date","open","high","low","close","volume"])
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(out)
    print(f"Downloaded {len(rows)} inspected adjusted bars across {len(args.symbols)} tickers")

if __name__ == "__main__":
    main()
