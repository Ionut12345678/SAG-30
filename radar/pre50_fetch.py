"""Fetch real daily OHLCV from Yahoo Finance for an explicit pilot universe.

Research feed only: coverage is reported; partial/missing histories fail closed.
"""
import argparse
import csv
import json
import math
from pathlib import Path
from radar.pre50_sessions import latest_completed_session
from radar.pre50 import load_csv


def fetch(symbols, out_dir, period="3y", now=None):
    import yfinance as yf
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    completed = latest_completed_session(now)
    errors, histories = {}, {}
    for symbol in symbols:
        try:
            frame = yf.Ticker(symbol).history(period=period, interval="1d",
                                              auto_adjust=False, actions=False)
            if frame is not None:
                frame = frame.loc[[ts.date().isoformat() <= completed for ts in frame.index]]
            if frame is None or len(frame) < 42:
                raise ValueError("Less than 42 daily bars")
            for ts, row in frame.iterrows():
                op, hi, lo, cl, vol = (float(row[k]) for k in ("Open", "High", "Low", "Close", "Volume"))
                if (not all(math.isfinite(v) for v in (op, hi, lo, cl, vol))
                    or min(op, hi, lo, cl) <= 0 or vol < 0
                    or lo > min(op, cl) or hi < max(op, cl) or lo > hi):
                    raise ValueError(f"Invalid OHLCV for {symbol} on {ts.date()}")
            path = out / f"{symbol}.csv"
            path.unlink(missing_ok=True)
            if frame.index[-1].date().isoformat() != completed:
                raise ValueError(f"Latest bar does not match completed session {completed}")
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("date", "open", "high", "low", "close", "volume"))
                for ts, row in frame.iterrows():
                    writer.writerow([ts.date().isoformat()] + [
                        float(row[k]) for k in ("Open", "High", "Low", "Close", "Volume")])
            validated = load_csv(path)
            histories[symbol] = {"rows": len(validated), "latest_session": validated[-1]["date"]}
        except Exception as exc:
            (out / f"{symbol}.csv").unlink(missing_ok=True)
            errors[symbol] = f"{type(exc).__name__}: {exc}"
    return {"requested": len(symbols), "fetched": len(symbols) - len(errors),
            "missing": errors, "expected_session": completed, "histories": histories, "provider": "yfinance_unofficial", "period": period}


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
