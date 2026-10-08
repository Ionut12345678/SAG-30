#!/usr/bin/env python3
"""SAG-30 independent, read-only winner recall audit. Never generates BUY."""
import argparse
import json
from collections import Counter
from pathlib import Path

def audit(report):
    winners = report["winners"]
    assert len({(x["session"], x["symbol"]) for x in winners}) == len(winners), "Duplicate symbol/session"
    n = len(winners)
    counts10 = Counter(x["classification_under_10"] for x in winners)
    counts20 = Counter(x["classification_under_20"] for x in winners)
    scout = sum(x.get("first_under_10_scout_ts") is not None for x in winners)
    shortlisted = sum(bool(x.get("any_selected_under_10")) for x in winners)
    hot = sum(x.get("r2_hot_under_10_ts") is not None for x in winners)
    examples = []
    for x in winners:
        t0 = x.get("first_under_10_scout_ts")
        t1 = x.get("first_30_ts")
        if t0 and t1:
            from datetime import datetime
            minutes = (datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds()/60
            if minutes < 0:
                raise ValueError("Nonchronological timestamps")
            examples.append({"session": x["session"], "symbol": x["symbol"],
                             "scout_pct_vs_prev_close": x["first_under_10_scout_pct"],
                             "scout_ts": t0, "first_30_ts": t1,
                             "lead_minutes": round(minutes, 2),
                             "selected_under_10": bool(x.get("any_selected_under_10")),
                             "miss_reason": x["classification_under_10"]})
    return {"status": "WINNER_ONLY_RECALL_NOT_PRECISION_NOT_BUY",
            "winner_sessions": n, "scout_under_10": scout,
            "shortlisted_under_10": shortlisted, "r2_hot_under_10": hot,
            "recall_scout": scout/n if n else None,
            "recall_shortlist": shortlisted/n if n else None,
            "miss_reasons_under_10": dict(counts10),
            "miss_reasons_under_20": dict(counts20),
            "chronological_scout_cases": examples,
            "limitations": ["Winner-selected cohort: no false-positive denominator",
                            "No executable bid/ask or entry fills",
                            "Thresholds are change vs previous close, not entry return",
                            "Do not modify v0.3.3 FROZEN or issue BUY"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("input", type=Path, help="winner_recall_report.json")
    p.add_argument("--output", type=Path)
    args=p.parse_args()
    result=audit(json.loads(args.input.read_text()))
    serialized=json.dumps(result, indent=2, ensure_ascii=False)+"\n"
    if args.output: args.output.write_text(serialized)
    else: print(serialized)
if __name__=="__main__":
    main()
