"""Prospective-feature-only benchmark on historical replay output.

Predeclared rules; do not optimize on this retrospective cohort.
No BUY, no live alerts, no claim of executable returns.
"""
import argparse
import json
from pathlib import Path

def classify(record):
    """Only entry-time fields. Never inspect peak, hits, outcome or subsequent bars."""
    if record.get("status")!="EVALUATED_HISTORICAL_REPLAY":
        return "NOT_EVALUABLE"
    volume=record.get("signal_volume_ratio_vs_prior_6")
    change=record.get("signal_change_pct")
    if volume is None:
        return "INSUFFICIENT_PRE_ENTRY_VOLUME"
    if not isinstance(volume,(int,float)) or isinstance(volume,bool):
        return "INVALID_FEATURE"
    if not isinstance(change,(int,float)) or isinstance(change,bool):
        return "INVALID_FEATURE"
    # Predeclared experimental filter: unusual current bar volume and
    # earliest-stage move. An explicit missing-data abstention.
    return "PASS" if volume>=2 and 5<=change<=8 else "REJECT"

def benchmark(records):
    results=[]
    for record in records:
        label=classify(record)
        if label=="NOT_EVALUABLE":continue
        is_winner=record.get("outcome")=="WINNER_20"
        results.append({"symbol":record.get("symbol"),"session":record.get("session"),
                        "classification":label,"historical_hit_20":is_winner,
                        "historical_return_upper_bound_pct":record.get("max_gain_from_proxy_entry_pct")})
    evaluated=[r for r in results if r["classification"] in ("PASS","REJECT")]
    passes=[r for r in evaluated if r["classification"]=="PASS"]
    wins=[r for r in evaluated if r["historical_hit_20"]]
    missing=sum(r["classification"]=="INSUFFICIENT_PRE_ENTRY_VOLUME" for r in results)
    return {"status":"RETROSPECTIVE_EXPERIMENT_NOT_VALIDATED",
            "rules_predeclared":True,"population":len(records),
            "replays_with_any_entry":len(results),"feature_evaluable":len(evaluated),
            "missing_volume_feature":missing,"experimental_passes":len(passes),
            "experimental_hit_20_count":sum(r["historical_hit_20"] for r in passes),
            "baseline_hit_20_count":len(wins),
            "baseline_hit_rate_pct":round(100*len(wins)/len(evaluated),2) if evaluated else None,
            "experimental_hit_rate_pct":round(100*sum(r["historical_hit_20"] for r in passes)/len(passes),2) if passes else None,
            "winner_capture_pct":round(100*sum(r["historical_hit_20"] for r in passes)/len(wins),2) if wins else None,
            "insufficient_to_select_model":len(evaluated)<100 or len(wins)<10,
            "lookahead_guard":"classification ignores future max, future threshold hits and outcome",
            "orders_enabled":False,"results":results}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default="historical-real-replay.json")
    p.add_argument("--out",default="historical-pattern-benchmark.json")
    args=p.parse_args()
    raw=json.loads(Path(args.input).read_text())
    records=raw.get("results",[]) if isinstance(raw,dict) else []
    report=benchmark(records)
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("feature_evaluable","experimental_passes","baseline_hit_20_count",
      "experimental_hit_20_count","insufficient_to_select_model")}))
if __name__=="__main__":main()
