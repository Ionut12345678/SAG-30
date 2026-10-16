"""Fetch real daily OHLCV from Yahoo Finance for an explicit pilot universe.

Research feed only: coverage is reported; partial/missing histories fail closed.
"""
import argparse
import csv
import json
import math
from pathlib import Path


def valid_ohlcv(values):
    if not all(math.isfinite(v) and v >= 0 for v in values):
        return False
    opening, high, low, close, volume = values
    return high > 0 and low <= min(opening, close) and high >= max(opening, close)


def fetch(symbols, out_dir, period="3y"):
    import yfinance as yf
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    errors = {}
    for symbol in symbols:
        try:
            frame = yf.Ticker(symbol).history(period=period, interval="1d",
                                              auto_adjust=False, actions=False)
            if frame is None or len(frame) < 42:
                raise ValueError("Less than 42 daily bars")
            for ts, row in frame.iterrows():
                values = [float(row[k]) for k in ("Open", "High", "Low", "Close", "Volume")]
                if not valid_ohlcv(values):
                    raise ValueError(f"INVALID_OHLCV: {symbol} {ts.date()}")
            path = out / f"{symbol}.csv"
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("date", "open", "high", "low", "close", "volume"))
                for ts, row in frame.iterrows():
                    writer.writerow([ts.date().isoformat()] + [
                        float(row[k]) for k in ("Open", "High", "Low", "Close", "Volume")])
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"
    return {"requested": len(symbols), "fetched": len(symbols) - len(errors),
            "missing": errors, "provider": "yfinance_unofficial", "period": period}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--coverage", required=True)
    args = p.parse_args()
    symbols = list(dict.fromkeys(s.strip().upper() for s in
                   Path(args.tickers).read_text().splitlines() if s.strip() and not s.startswith("#")))
    if not symbols:
        raise SystemExit("DATA_GAP: empty pilot universe")
    report = fetch(symbols, args.out_dir)
    Path(args.coverage).write_text(json.dumps(report, indent=2) + "\n")
    if report["missing"]:
        raise SystemExit(f"DATA_GAP: {report['fetched']}/{report['requested']} symbols fetched")


if __name__ == "__main__":
    main()
