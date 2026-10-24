"""Fetch daily CSV OHLC from Stooq; explicit errors, no fabricated fallback."""
import argparse
import csv
import io
import re
import urllib.request
from datetime import date
from pathlib import Path

SYMBOL = re.compile(r"^[a-z0-9.]{1,16}$", re.I)
HEADER = ["Date", "Open", "High", "Low", "Close", "Volume"]

def fetch(symbol: str, start: str, end: str) -> list[dict]:
    if not SYMBOL.fullmatch(symbol):
        raise ValueError("Invalid ticker")
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a > b or b > date.today():
        raise ValueError("Invalid date window")
    ticker = symbol.lower() if symbol.lower().endswith(".us") else symbol.lower() + ".us"
    url = (f"https://stooq.com/q/d/l/?s={ticker}&i=d&d1={a:%Y%m%d}&d2={b:%Y%m%d}")
    request = urllib.request.Request(url, headers={"User-Agent": "Radar100-research/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(12_000_000).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames != HEADER:
        raise ValueError("Unexpected Stooq format; data not trusted")
    rows = []
    for row in reader:
        d = date.fromisoformat(row["Date"])
        vals = {k: float(row[k]) for k in ("Open", "High", "Low", "Close", "Volume")}
        if d < a or d > b or min(vals.values()) < 0 or min(vals[k] for k in ("Open", "High", "Low", "Close")) <= 0:
            raise ValueError("Out of range or invalid price data")
        if vals["High"] < max(vals[k] for k in ("Open", "Close", "Low")) or vals["Low"] > min(vals[k] for k in ("Open", "Close")):
            raise ValueError("Inconsistent OHLC")
        rows.append({"symbol":symbol.upper().replace(".US",""),"date":d.isoformat(),
                     **{k.lower(): row[k] for k in ("Open", "High", "Low", "Close")},
                     "volume":row["Volume"]})
    if not rows or len(set(r["date"] for r in rows)) != len(rows):
        raise ValueError("No data or duplicate dates")
    rows.sort(key=lambda r:r["date"])
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--out", default="prices.csv")
    a = p.parse_args()
    symbols = [s.upper() for s in a.symbols]
    if len(set(symbols)) != len(symbols):
        p.error("Duplicate symbols")
    # Fail closed: write only after ALL downloads and validations succeed.
    rows = []
    for symbol in symbols:
        bars = fetch(symbol, a.start, a.end)
        if len(bars) < 100:
            raise RuntimeError(f"{symbol}: insufficient historical bars ({len(bars)})")
        rows.extend(bars)
    output = Path(a.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol","date","open","high","low","close","volume"])
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(output)
    print(f"Saved {len(rows)} validated daily bars for {len(symbols)} symbols to {output}")

if __name__ == "__main__":
    main()
