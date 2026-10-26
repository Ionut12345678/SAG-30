"""Leakage-conscious daily-bar baseline. Research only, no order execution.

Signals use close at day t, available only AFTER that close. Forward returns
are close(t+h)/close(t)-1, excluding costs; NOT executable at close(t).
"""
import argparse
import json
import math
from pathlib import Path

def backtest(rows, lookback=20, horizon=20, threshold=0.05):
    grouped={}
    for r in rows:
        price=r.get("close")
        volume=r.get("volume")
        if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
            continue
        if not isinstance(volume,(int,float)) or not math.isfinite(volume) or volume<0:
            continue
        grouped.setdefault(r["symbol"],[]).append(r)
    all_signals=[]
    for symbol, bars in sorted(grouped.items()):
        bars.sort(key=lambda x:x["source_ts"])
        if len(set(b["source_ts"] for b in bars))!=len(bars):
            raise ValueError("duplicate bars: "+symbol)
        for i in range(lookback,len(bars)-horizon):
            past=bars[i-lookback]["close"]
            momentum=bars[i]["close"]/past-1
            if momentum<threshold:continue
            forward=bars[i+horizon]["close"]/bars[i]["close"]-1
            all_signals.append({"symbol":symbol,"signal_ts":bars[i]["source_ts"],
                "momentum_pct":round(momentum*100,4),
                "future_return_pct":round(forward*100,4),
                "horizon_sessions":horizon})
    winners=sum(x["future_return_pct"]>0 for x in all_signals)
    return {"warning":"exploratory, overlapping signals, selected symbols, no fees/spread/slippage, close not executable after signal",
        "lookback_sessions":lookback,"horizon_sessions":horizon,"threshold_pct":threshold*100,
        "signal_count":len(all_signals),"positive_count":winners,
        "positive_fraction":winners/len(all_signals) if all_signals else None,
        "signals":all_signals}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    files=sorted(Path(a.input_dir).glob("*_daily.jsonl"))
    if not files:raise SystemExit("no data")
    rows=[json.loads(line) for f in files for line in f.read_text().splitlines() if line.strip()]
    result=backtest(rows)
    Path(a.output).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("BASELINE_SIGNALS",result["signal_count"],"POSITIVE",result["positive_count"])
if __name__=="__main__":main()
