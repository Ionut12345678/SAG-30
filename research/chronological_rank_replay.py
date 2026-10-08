#!/usr/bin/env python3
"""Chronological replay for recorded SCOUT snapshots; SHADOW only.

Input JSONL: one object per observed scout candidate with:
 ts (ISO UTC), symbol, session, rank (rank known at ts), selected (bool),
 optional observed_30_after_ts, observed_50_after_ts (evaluation labels only).
 Never use outcome fields for ranking, and never synthesize missing bars.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

def dt(s):
    t=datetime.fromisoformat(s.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("timestamps must be timezone-aware")
    return t.astimezone(timezone.utc)

def replay(rows, cutoffs=(60,80,100,120)):
    rows=sorted(rows,key=lambda x:dt(x["ts"]))
    if any("rank" not in x or "session" not in x or "symbol" not in x for x in rows):
        raise ValueError("Each row needs rank, session and symbol")
    # An observed outcome is not a verified negative; only future labels count.
    by_key={}
    for row in rows:
        by_key.setdefault((row["session"],row["symbol"]),[]).append(row)
    results=[]
    for cutoff in cutoffs:
        first={}
        baseline=set()
        for row in rows:
            key=(row["session"],row["symbol"])
            if row.get("selected"): baseline.add(key)
            if row["rank"] is not None and row["rank"]<=cutoff and key not in first:
                first[key]=row
        hits30=hits50=0
        known30=known50=0
        for key,row in first.items():
            entry=dt(row["ts"])
            for label,hit in (("observed_30_after_ts",30),("observed_50_after_ts",50)):
                future=[dt(x[label]) for x in by_key[key] if x.get(label) and dt(x[label])>entry]
                if future:
                    if hit==30: known30+=1;hits30+=1
                    else: known50+=1;hits50+=1
        results.append({"rank_cutoff":cutoff,"unique_alerts":len(first),
                        "baseline_unique_selected":len(baseline),
                        "observed_30_after_alert":hits30,"known_30_labels":known30,
                        "observed_50_after_alert":hits50,"known_50_labels":known50,
                        "note":"Missing outcome labels are UNKNOWN, not negatives; quote/fill not validated"})
    if any(row["rank"] is None for row in rows):
        for result in results:
            result["incomplete_rank_coverage"]=True
    return {"status":"CHRONOLOGICAL_SHADOW_NOT_BUY","rows":len(rows),"results":results,
            "limitations":["Requires true timestamped ranks for ALL candidates, not retrospective best ranks",
                           "Outcomes evaluated only after alert; no BUY, fills or net return",
                           "No meaningful precision until full outcomes including negatives are supplied"]}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("scout_jsonl",type=Path)
    a=p.parse_args()
    rows=[json.loads(line) for line in a.scout_jsonl.read_text().splitlines() if line.strip()]
    print(json.dumps(replay(rows),indent=2))
