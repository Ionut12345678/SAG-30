"""Radar100: offline, long-only, next-open execution backtest. No broker access."""
import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

COST_BPS = 10  # per fill (fees + conservative slippage), configurable
START = 100.0

def load(path):
    grouped = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        needed = {"symbol", "date", "open", "high", "low", "close"}
        if not reader.fieldnames or not needed.issubset(reader.fieldnames):
            raise ValueError("CSV needs symbol,date,open,high,low,close")
        for r in reader:
            d = date.fromisoformat(r["date"])
            vals = {k: float(r[k]) for k in ("open", "high", "low", "close")}
            if min(vals.values()) <= 0 or vals["high"] < max(vals["open"], vals["close"], vals["low"]) or vals["low"] > min(vals["open"], vals["close"]):
                raise ValueError("Bad OHLC data at " + str(d))
            grouped[r["symbol"]].append({"date": d, **vals})
    for symbol, bars in grouped.items():
        bars.sort(key=lambda x: x["date"])
        if len({x["date"] for x in bars}) != len(bars):
            raise ValueError("Duplicate date for " + symbol)
    return grouped

def test_signal(bars, t):
    # All observations end at the close of t; never use t+1 in signal.
    if t < 60:
        return False
    close = bars[t]["close"]
    ma20 = mean(x["close"] for x in bars[t-19:t+1])
    ma60 = mean(x["close"] for x in bars[t-59:t+1])
    return close > ma20 > ma60 and close / bars[t-20]["close"] >= 1.03

def backtest(bars, cost_bps=COST_BPS, horizon=10, size=20., stop_pct=.05,
             dca=False, capital=START):
    if cost_bps < 0 or horizon < 1 or size <= 0 or capital <= 0 or not 0 < stop_pct < 1:
        raise ValueError("Invalid parameters")
    if dca:
        # DCA adds no exposure beyond initial 20 EUR position cap.
        weights = [0.5, 0.3, 0.2]
    else:
        weights = [1.0]
    cash = capital
    trades = []
    # Sequential per-symbol trades. No overlapping trades on same symbol;
    # multi-symbol portfolio scheduling intentionally NOT modeled.
    t = 60
    while t + horizon + 1 < len(bars):
        if not test_signal(bars, t):
            t += 1
            continue
        first = bars[t+1]["open"]
        if first <= 0 or cash < size:
            t += 1
            continue
        budget = min(size, cash)
        fills = [(first, budget * weights[0])]
        qty = fills[0][1] / first
        entry_cost = fills[0][1] * cost_bps / 10000
        anchor = first
        filled = {0}
        exit_index = min(t + horizon, len(bars) - 1)
        exit_price = bars[exit_index]["close"]
        reason = "horizon"
        for j in range(t+1, exit_index+1):
            bar = bars[j]
            if j > t+1 and bar["open"] <= anchor * (1-stop_pct):
                exit_price, exit_index, reason = bar["open"], j, "stop_gap"
                break
            if bar["low"] <= anchor * (1-stop_pct):
                exit_price, exit_index, reason = anchor * (1-stop_pct), j, "stop"
                break
            if dca and j > t+1:
                # Limit orders only after entry, pessimistic next-day placement.
                for idx, threshold in ((1, .97), (2, .94)):
                    if idx not in filled and bar["low"] <= anchor * threshold:
                        price = min(bar["open"], anchor * threshold)
                        stake = budget * weights[idx]
                        qty += stake / price
                        entry_cost += stake * cost_bps / 10000
                        fills.append((price, stake))
                        filled.add(idx)
        deployed = sum(stake for _, stake in fills)
        proceeds = qty * exit_price
        pnl = proceeds - deployed - entry_cost - proceeds * cost_bps / 10000
        cash += pnl
        trades.append({"signal_date": str(bars[t]["date"]),
                       "entry_date": str(bars[t+1]["date"]),
                       "exit_date": str(bars[exit_index]["date"]),
                       "entry_price": first, "exit_price": exit_price,
                       "filled_eur": round(deployed, 4),
                       "pnl_eur": round(pnl, 4), "exit_reason": reason})
        t = exit_index + 1
    return {"trades": trades, "final_eur": round(cash, 4),
            "net_return_pct": round((cash/capital-1)*100, 4),
            "trade_count": len(trades), "wins": sum(x["pnl_eur"] > 0 for x in trades),
            "cost_bps_per_side": cost_bps,
            "limitations": "One-symbol sequential trade simulation; no portfolio allocation, taxes, live pricing, or broker integration."}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv", help="Daily OHLC CSV with symbol,date,open,high,low,close")
    p.add_argument("--symbol", required=True)
    p.add_argument("--dca", action="store_true")
    p.add_argument("--cost-bps", type=float, default=COST_BPS)
    p.add_argument("--out", default="")
    a = p.parse_args()
    group = load(a.csv)
    if a.symbol not in group:
        p.error("Symbol not found in CSV")
    result = {"symbol": a.symbol, "mode": "DCA" if a.dca else "single_entry",
              **backtest(group[a.symbol], cost_bps=a.cost_bps, dca=a.dca)}
    payload = json.dumps(result, indent=2)
    if a.out:
        Path(a.out).write_text(payload + "\n", encoding="utf-8")
    print(payload)

if __name__ == "__main__":
    main()
