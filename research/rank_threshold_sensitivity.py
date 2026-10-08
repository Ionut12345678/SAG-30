#!/usr/bin/env python3
"""SAG-30 read-only rank-threshold research. No live signals, no BUY."""
import argparse
import json
from pathlib import Path

def evaluate(report):
    winners=report["winners"]
    n=len(winners)
    baseline=sum(bool(x["any_selected_under_10"]) for x in winners)
    results=[]
    for cutoff in (60,80,100,120):
        recovered=[x for x in winners if not x["any_selected_under_10"]
                   and x["first_under_10_scout_ts"] is not None
                   and x.get("best_multi_engine_rank_under_10") is not None
                   and x["best_multi_engine_rank_under_10"]<=cutoff]
        results.append({"cutoff":cutoff,"baseline":baseline,
                        "recovered":len(recovered),
                        "recall_upper_bound":(baseline+len(recovered))/n,
                        "symbols":[x["symbol"] for x in recovered]})
    return {"status":"RETROSPECTIVE_ORACLE_ONLY_NOT_LIVE_NOT_BUY",
            "winner_sessions":n,"results":results,
            "warning":"Best pre-30 ranks are hindsight maxima; cannot infer live threshold precision, cost or fills."}
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("report",type=Path)
    args=p.parse_args()
    print(json.dumps(evaluate(json.loads(args.report.read_text())),indent=2))
