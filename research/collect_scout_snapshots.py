#!/usr/bin/env python3
"""SAG-30 shadow snapshot collector. Read-only inputs, no trading.
Append-only per-run JSONL; preserve UNKNOWN rank rather than infer it.
Usage: python research/collect_scout_snapshots.py candidate_v034_report.json --output snapshots.jsonl
"""
import argparse, json
from pathlib import Path
from datetime import datetime, timezone

def iso(value):
    if not value: raise ValueError("missing timestamp")
    t=datetime.fromisoformat(value.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("naive timestamp")
    return t.astimezone(timezone.utc).isoformat()

def collect(report):
    result=[]
    for row in report.get("scout_to_deep",[]):
        ts=iso(row["scout_ts"])
        session=ts[:10]
        result.append({"session":session,"symbol":row["symbol"],"ts":ts,
                       "rank":row.get("rank_at_scout"),
                       "selected":row.get("deep_retrieval_ts") is not None,
                       "scout_pct_vs_prev_close":row.get("scout_change_pct"),
                       "deep_ts":row.get("deep_retrieval_ts"),
                       "rank_quality":"OBSERVED" if row.get("rank_at_scout") is not None else "UNKNOWN",
                       "source":"candidate_v034_report.scout_to_deep",
                       "status":"SHADOW_NOT_BUY"})
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("report",type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    rows=collect(json.loads(a.report.read_text()))
    prior=[]
    if a.output.exists():
        prior=[json.loads(line) for line in a.output.read_text().splitlines() if line.strip()]
    unique={(x["session"],x["symbol"],x["ts"]):x for x in prior}
    for x in rows: unique.setdefault((x["session"],x["symbol"],x["ts"]),x)
    values=sorted(unique.values(),key=lambda x:(x["ts"],x["symbol"]))
    a.output.write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in values))
    print(json.dumps({"input_rows":len(rows),"stored_rows":len(values),
                      "rank_known":sum(x["rank"] is not None for x in values),
                      "rank_unknown":sum(x["rank"] is None for x in values),
                      "status":"SHADOW_NOT_BUY"}))
if __name__=="__main__": main()
