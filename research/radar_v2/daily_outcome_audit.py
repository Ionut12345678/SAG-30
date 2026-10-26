"""Exploratory daily-bar outcome audit; not a live radar or tradable backtest.

Measures forward *daily close* returns from each historical observation.
Overlapping windows are descriptive and must not be interpreted as independent trades.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

LEVELS=(15,20,30,50)
HORIZONS=(5,20,60)
def audit(rows):
    by_symbol={}
    for r in rows:
        if not isinstance(r.get("close"),(int,float)) or not math.isfinite(r["close"]) or r["close"]<=0:
            continue
        by_symbol.setdefault(r["symbol"],[]).append(r)
    results={}
    for symbol,items in sorted(by_symbol.items()):
        items.sort(key=lambda r:r["source_ts"])
        if len({r["source_ts"] for r in items})!=len(items):
            raise ValueError("duplicate timestamp for "+symbol)
        result={"observations":len(items),"horizons":{}}
        for horizon in HORIZONS:
            outcomes=[(items[i+horizon]["close"]/items[i]["close"]-1)*100 for i in range(max(0,len(items)-horizon))]
            result["horizons"][str(horizon)]={"samples":len(outcomes),
                "positive":sum(x>0 for x in outcomes),
                "touches_at_horizon":{str(level):sum(x>=level for x in outcomes) for level in LEVELS}}
        results[symbol]=result
    return {"method":"daily-close forward outcome; overlapping windows; not causal signal performance",
            "symbols":results}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    paths=sorted(Path(a.input_dir).glob("*_daily.jsonl"))
    if not paths: raise SystemExit("no input files")
    rows=[json.loads(line) for path in paths for line in path.read_text().splitlines() if line.strip()]
    report=audit(rows)
    Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("AUDITED_SYMBOLS",len(report["symbols"]),"ROWS",len(rows))
if __name__=="__main__":main()
