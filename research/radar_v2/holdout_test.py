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
        benchmark={"train":[], "holdout":[]}
        reference={"train":[], "holdout":[]}
        for i in range(lookback,len(bars)-horizon):
            group="train" if i+horizon<split else ("holdout" if i>=split else None)
            if group is None:continue
            entry=bars[i+1]["open"]
            if entry<=0:raise ValueError("invalid open")
            benchmark[group].append(100*(bars[i+horizon]["close"]/entry-1))
            if bars[i]["close"]/bars[i-lookback]["close"]-1 < threshold:
                continue
            stats[group].append(100*(bars[i+horizon]["close"]/entry-1))
            reference[group].append(100*(bars[i+horizon]["close"]/bars[i]["close"]-1))
        summary[symbol]={key:{"count":len(vals),"positive":sum(v>0 for v in vals),
            "mean_pct":round(sum(vals)/len(vals),3) if vals else None}
            for key,vals in stats.items()}
        summary[symbol]["all_dates_reference"]={key:{"count":len(vals),"mean_pct":round(sum(vals)/len(vals),3) if vals else None} for key,vals in benchmark.items()}
        summary[symbol]["note"]="all_dates_reference enters every eligible day at next open; overlapping windows, not buy-and-hold"
    totals={}
    for part in ("train","holdout"):
        selected_count=sum(summary[symbol][part]["count"] for symbol in summary)
        selected_positive=sum(summary[symbol][part]["positive"] for symbol in summary)
        baseline_count=sum(summary[symbol]["all_dates_reference"][part]["count"] for symbol in summary)
        selected_weighted=sum(summary[symbol][part]["mean_pct"]*summary[symbol][part]["count"]
            for symbol in summary if summary[symbol][part]["mean_pct"] is not None)
        baseline_weighted=sum(summary[symbol]["all_dates_reference"][part]["mean_pct"]*
            summary[symbol]["all_dates_reference"][part]["count"] for symbol in summary
            if summary[symbol]["all_dates_reference"][part]["mean_pct"] is not None)
        selected_mean=selected_weighted/selected_count if selected_count else None
        baseline_mean=baseline_weighted/baseline_count if baseline_count else None
        totals[part]={"count":selected_count,"positive":selected_positive,
            "selected_mean_pct":round(selected_mean,3) if selected_mean is not None else None,
            "all_dates_mean_pct":round(baseline_mean,3) if baseline_mean is not None else None,
            "excess_pct_points":round(selected_mean-baseline_mean,3)
                if selected_mean is not None and baseline_mean is not None else None,
            "selected_mean_after_0_2pct_roundtrip_cost":round(selected_mean-0.2,3)
                if selected_mean is not None else None}
    return {"totals":totals,"caveat":"overlapping signals, survivor sample, no trading costs", "symbols":summary}

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
