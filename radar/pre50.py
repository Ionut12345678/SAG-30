"""PRE50 v0.1 research scanner from PRE50_documentatie.pdf (2026-10-15).

Uncalibrated daily OHLCV precursor. NEVER executes trades. No SAG-30 BUY changes.
Normalization choices below are explicit implementation hypotheses, not in the PDF.
"""
import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

WEIGHTS = {"rvol": 25, "acceleration": 20, "compression": 15,
           "near_high": 15, "volume_trend": 15, "close_location": 10}
THRESHOLDS = {"WATCH": 45, "PRIORITY": 65, "ALERT": 75}
TARGET = 0.50


def clamp(x):
    return max(0.0, min(1.0, x))


def mean(values):
    return sum(values) / len(values) if values else 0.0


def true_range(cur, previous_close):
    return max(cur["high"] - cur["low"], abs(cur["high"] - previous_close),
               abs(cur["low"] - previous_close))


def evaluate(bars, i):
    """Only use data through bar i; return None for ineligible rows."""
    if i < 40:
        return None
    row = bars[i]
    close = row["close"]
    if not (0.50 <= close <= 30.0):
        return None
    dollar_volume = mean([x["close"] * x["volume"] for x in bars[i-4:i+1]])
    if dollar_volume < 300000:
        return None
    prev_close = bars[i-1]["close"]
    if prev_close <= 0 or close / prev_close - 1 >= 0.80:
        return None
    vol20 = mean([x["volume"] for x in bars[i-20:i]])
    vol3 = mean([x["volume"] for x in bars[i-2:i+1]])
    vol20_lag = mean([x["volume"] for x in bars[i-22:i-2]])
    if vol20 <= 0 or vol20_lag <= 0 or bars[i-3]["close"] <= 0:
        return None
    tr = [true_range(bars[j], bars[j-1]["close"]) for j in range(i-19, i+1)]
    atr5, atr20 = mean(tr[-5:]), mean(tr)
    if atr20 <= 0:
        return None
    high20 = max(x["high"] for x in bars[i-19:i+1])
    day_range = row["high"] - row["low"]
    rvol = row["volume"] / vol20
    accel = close / bars[i-3]["close"] - 1
    compression = atr5 / atr20
    near = close / high20 if high20 > 0 else 0
    trend = vol3 / vol20_lag
    location = (close - row["low"]) / day_range if day_range > 0 else 0
    # Uncalibrated monotonic/triangular maps: PDF specifies only weights
    # and the points of maximum score, not full normalization curves.
    features = {
        "rvol": clamp(rvol / 6),
        "acceleration": clamp(accel / .08) if accel < .08 else
                        (1.0 if accel <= .40 else clamp((.80 - accel) / .40)),
        "compression": clamp(.6 / compression) if compression > 0 else 1.0,
        "near_high": clamp((near - .85) / .15),
        "volume_trend": clamp(trend / 3),
        "close_location": clamp(location / .9),
    }
    score = round(sum(WEIGHTS[k] * features[k] for k in WEIGHTS), 3)
    tier = "ALERT" if score >= 75 else "PRIORITY" if score >= 65 else (
        "WATCH" if score >= 45 else "NONE")
    return {"date": row["date"], "close": close, "score": score, "tier": tier,
            "features": {k: round(v, 4) for k, v in features.items()},
            "rvol": round(rvol, 3), "accel_3d_pct": round(accel * 100, 3),
            "dollar_volume_5d": round(dollar_volume, 2)}


def load_csv(path):
    """Input format: date,open,high,low,close,volume; chronological, raw OHLCV."""
    rows = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            item = {"date": row["date"]}
            for k in ("open", "high", "low", "close", "volume"):
                item[k] = float(row[k])
                if not math.isfinite(item[k]) or item[k] < 0:
                    raise ValueError(f"Invalid {k} in {path}")
            if not (item["low"] <= item["close"] <= item["high"]
                    and item["low"] <= item["open"] <= item["high"]
                    and item["high"] > 0):
                raise ValueError(f"Invalid OHLC in {path} on {item['date']}")
            rows.append(item)
    if len({x["date"] for x in rows}) != len(rows):
        raise ValueError(f"Duplicate dates in {path}")
    if [x["date"] for x in rows] != sorted(x["date"] for x in rows):
        raise ValueError(f"Unsorted dates in {path}")
    return rows


def load_universe(directory, tickers):
    """Require explicit per-ticker OHLCV files; missing symbols are DATA_GAP."""
    out, missing = {}, []
    for symbol in tickers:
        path = Path(directory) / (symbol + ".csv")
        if not path.exists():
            missing.append(symbol)
        else:
            out[symbol] = load_csv(path)
    return out, missing


def backtest(universe):
    """Walk-forward one-session label; baseline on same eligible denominator."""
    totals = {"eligible": 0, "events": 0}
    tiers = {k: {"alerts": 0, "hits": 0} for k in THRESHOLDS}
    for bars in universe.values():
        for i in range(40, len(bars) - 1):
            scored = evaluate(bars, i)
            if scored is None:
                continue
            totals["eligible"] += 1
            event = bars[i+1]["high"] / bars[i]["close"] - 1 >= TARGET
            totals["events"] += int(event)
            for tier, threshold in THRESHOLDS.items():
                if scored["score"] >= threshold:
                    tiers[tier]["alerts"] += 1
                    tiers[tier]["hits"] += int(event)
    base = totals["events"] / totals["eligible"] if totals["eligible"] else None
    for result in tiers.values():
        precision = result["hits"] / result["alerts"] if result["alerts"] else None
        result["precision"] = precision
        result["lift"] = precision / base if precision is not None and base else None
        result["recall"] = result["hits"] / totals["events"] if totals["events"] else None
    return {"target": "high_t_plus_1 / close_t - 1 >= 0.50", "baseline": base,
            "totals": totals, "tiers": tiers, "uncalibrated": True,
            "warning": "Fewer than 30 eligible events: inconclusive" if totals["events"] < 30 else None}


def scan(universe):
    """Require common latest session date; don't silently mix different days."""
    latest = max((bars[-1]["date"] for bars in universe.values() if bars), default=None)
    candidates, stale = [], []
    for symbol, bars in universe.items():
        if not bars or bars[-1]["date"] != latest:
            stale.append(symbol)
            continue
        result = evaluate(bars, len(bars)-1)
        if result and result["tier"] != "NONE":
            candidates.append({"symbol": symbol, **result})
    candidates.sort(key=lambda x: (-x["score"], x["symbol"]))
    return {"as_of": latest, "mode": "SHADOW_ONLY", "buy": False,
            "candidates": candidates, "stale_symbols": stale}


def resolve(journal, universe):
    """Only actual next chronological bar after the alert date can resolve."""
    for event in journal:
        if event.get("resolved") is not None:
            continue
        bars = universe.get(event["symbol"], [])
        subsequent = [b for b in bars if b["date"] > event["date"]]
        if not subsequent:
            continue
        nxt = subsequent[0]
        event["resolved"] = {"next_date": nxt["date"], "next_high": nxt["high"],
                             "change_pct": round((nxt["high"] / event["close"] - 1) * 100, 4),
                             "hit_50": nxt["high"] / event["close"] - 1 >= TARGET,
                             "high_is_executable": False}
    return journal


def main():
    p = argparse.ArgumentParser(description="PRE50 daily research scanner; NO TRADES")
    p.add_argument("command", choices=("backtest", "scan", "resolve"))
    p.add_argument("--data-dir", required=True, help="Directory of SYMBOL.csv OHLCV files")
    p.add_argument("--tickers", required=True, help="Text file, one ticker per line")
    p.add_argument("--journal", default="pre50-journal.json")
    p.add_argument("--live-session", action="store_true", help="Require the latest completed exchange session")
    p.add_argument("--expected-session", help="Required US trading session YYYY-MM-DD for prospective scan")
    p.add_argument("--output", default="pre50-report.json")
    args = p.parse_args()
    tickers = list(dict.fromkeys(x.strip().upper() for x in
                  Path(args.tickers).read_text().splitlines() if x.strip() and not x.startswith("#")))
    universe, missing = load_universe(args.data_dir, tickers)
    if missing or not universe:
        raise SystemExit(f"DATA_GAP: {len(missing)} missing OHLCV files of {len(tickers)}: {missing[:10]}")
    expected = args.expected_session
    if args.live_session:
        from radar.pre50_sessions import latest_completed_session
        expected = latest_completed_session()
        universe = {symbol: [b for b in bars if b["date"] <= expected]
                    for symbol, bars in universe.items()}
    if expected and args.command != "backtest":
        stale = [s for s, bars in universe.items() if not bars or bars[-1]["date"] != expected]
        if stale:
            raise SystemExit(f"DATA_GAP: expected completed session {expected}: {stale[:10]}")
    if args.command == "backtest":
        report = backtest(universe)
    elif args.command == "scan":
        report = scan(universe)
        if expected and report["as_of"] != expected:
            raise SystemExit(f"DATA_GAP: latest session {report['as_of']} != expected {expected}")
        if report["stale_symbols"] or not report["as_of"]:
            raise SystemExit(f"DATA_GAP: stale symbols {report['stale_symbols'][:10]}")
        path = Path(args.journal)
        journal = json.loads(path.read_text()) if path.exists() else []
        existing = {(e["symbol"], e["date"]) for e in journal}
        for item in report["candidates"]:
            if (item["symbol"], item["date"]) not in existing:
                journal.append({"symbol": item["symbol"], "date": item["date"],
                                "close": item["close"], "score": item["score"],
                                "tier": item["tier"], "resolved": None,
                                "first_recorded_at": datetime.now(timezone.utc).isoformat()})
        path.write_text(json.dumps(journal, indent=2) + "\n")
    else:
        path = Path(args.journal)
        if not path.exists():
            raise SystemExit("DATA_GAP: journal does not exist")
        journal = resolve(json.loads(path.read_text()), universe)
        path.write_text(json.dumps(journal, indent=2) + "\n")
        report = {"mode": "SHADOW_ONLY", "buy": False, "journal": journal}
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"command": args.command, "status": "OK",
                      "symbols": len(universe), "output": args.output}))


if __name__ == "__main__":
    main()
