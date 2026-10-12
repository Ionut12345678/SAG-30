"""Honest winner-first failure funnel from the persisted SAG-30 report.

This is retrospective diagnostics, NOT a trained classifier, forward validation
or a real-time trading signal. No target labels are fed back to production.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

STAGES = ("SCOUT_MISS","SHORTLIST_MISS","DEEP_TIMING_MISS",
          "BASELINE_MISS","MODEL_MISS","EARLY_HOT_SUCCESS")


def audit(report):
    winners = report.get("winners")
    if not isinstance(winners, list):
        raise ValueError("Expected winners array")
    keys = [(w["session"], w["symbol"]) for w in winners]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate winner symbol-session")
    buckets = Counter()
    invalid = []
    records = []
    for w in winners:
        cls = w.get("classification_under_10")
        if cls not in STAGES:
            invalid.append({"session": w["session"], "symbol": w["symbol"], "class": cls})
            continue
        buckets[cls] += 1
        earlier = w.get("first_under_10_scout_ts")
        target = w.get("first_30_ts")
        if earlier is not None and target is not None and earlier >= target:
            invalid.append({"session":w["session"],"symbol":w["symbol"],"class":"NON_CAUSAL_TIMESTAMP"})
        records.append({"session":w["session"],"symbol":w["symbol"],
                        "failure_stage":cls,
                        "first_30_ts":target,
                        "first_30_pct":w.get("first_30_pct"),
                        "pre10_scout_ts":earlier,
                        "base_selected_under_10":bool(w.get("base_selected_under_10")),
                        "any_selected_under_10":bool(w.get("any_selected_under_10")),
                        "earliest_available_before_10":"UNKNOWN_IF_SCOUT_MISS" if cls=="SCOUT_MISS" else "OBSERVED_BY_SCOUT",
                        "coverage_cause":"UNRESOLVED" if cls=="SCOUT_MISS" else "NOT_APPLICABLE"})
    counts = {s:buckets[s] for s in STAGES}
    n=len(winners)
    claimed = report.get("classification_counts_under_10")
    if isinstance(claimed,dict) and any(int(claimed.get(k,0))!=v for k,v in counts.items()):
        invalid.append({"class":"AGGREGATE_MISMATCH"})
    return {"status":"REQUIRES_REVIEW" if invalid else "RETROSPECTIVE_DIAGNOSTIC_ONLY",
            "winner_sessions":n,"classification_counts":counts,
            "fractions":{s:(round(counts[s]/n,4) if n else None) for s in STAGES},
            "scout_miss_causes_known":0,
            "scout_miss_causes_unresolved":counts["SCOUT_MISS"],
            "unknown_cause_note":"SCOUT_MISS does not establish a provider gap or filter defect. Reconstruct earliest available source observation before diagnosing.",
            "invalid_rows":invalid,
            "records":records,
            "no_buy":True}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=audit(json.loads(a.input.read_text(encoding="utf-8")))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="records"},sort_keys=True))
    if result["invalid_rows"]:
        raise SystemExit(2)


if __name__=="__main__":
    main()
