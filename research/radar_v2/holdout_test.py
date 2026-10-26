"""Chronological holdout diagnostic. Research only; no trades."""
import argparse
import json
from pathlib import Path

def evaluate(rows, lookback=20, horizon=20, threshold=0.05):
    grouped={}
    for row in rows:
        grouped.setdefault(row["symbol"], []).append(row)
    summary={}
    for symbol, bars in grouped.items():
        bars.sort(key=lambda x:x["source_ts"])
        if len(set(b["source_ts"] for b in bars)) != len(bars):
            raise ValueError("duplicate timestamps")
        split=int(len(bars)*0.7)
        stats={"train":[], "holdout":[]}
        for i in range(lookback,len(bars)-horizon):
            group="train" if i+horizon<split else ("holdout" if i>=split else None)
            if group is None:continue
            if bars[i]["close"]/bars[i-lookback]["close"]-1 < threshold:continue
            entry=bars[i+1]["open"]
            if entry<=0:raise ValueError("invalid open")
            stats[group].append(100*(bars[i+horizon]["close"]/entry-1))
        summary[symbol]={key:{"count":len(vals),"positive":sum(v>0 for v in vals),
            "mean_pct":round(sum(vals)/len(vals),3) if vals else None}
            for key,vals in stats.items()}
    return {"caveat":"overlapping signals, survivor sample, no trading costs", "symbols":summary}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    rows=[json.loads(line) for f in Path(args.input_dir).glob("*_daily.jsonl")
          for line in f.read_text().splitlines() if line.strip()]
    report=evaluate(rows)
    Path(args.output).write_text(json.dumps(report,indent=2)+"\n")
    print("HOLDOUT_SIGNALS",sum(v["holdout"]["count"] for v in report["symbols"].values()))
