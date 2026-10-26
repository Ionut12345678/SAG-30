"""Audit-only summary of prospective evidence; no trading or inferred returns."""
import argparse
import json
from collections import Counter
from pathlib import Path

def summarize(path):
    p=Path(path)
    events=[json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
    by_kind=Counter(x["kind"] for x in events)
    first={}
    validated=set()
    for e in events:
        if e["kind"]=="discovery":
            first.setdefault(e["symbol"],e["first_seen"])
        if e["kind"]=="validated_signal":
            validated.add(e["symbol"])
    return {"mode":"SHADOW","ledger_records":len(events),"discoveries":by_kind["discovery"],
            "validated_signals":by_kind["validated_signal"],"unique_validated_symbols":len(validated),
            "followups":by_kind["followup"],"first_seen_by_symbol":first,
            "milestones_confirmed":{str(k):0 for k in (15,20,30,50)},
            "note":"Milestones are not inferred from discoveries or historical replay."}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    report=summarize(args.ledger)
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("PROSPECTIVE_REPORT",json.dumps(report,sort_keys=True))
