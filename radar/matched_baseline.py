"""Matched simple-rule vs SAG-30 scout shortlist research comparison.

Uses only recorded prospective scout snapshots. No BUY or execution inference.
Both rules see exactly the same symbol-session history and outcome labels.
"""
import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def compare(rows, now=None):
    now=now or datetime.now(timezone.utc)
    now_et=now.astimezone(ZoneInfo("America/New_York"))
    grouped=defaultdict(list)
    for item in rows:
        grouped[(item["session"],item["symbol"])].append(item)
    tally={name:{"alerts":0,"observed_later_30":0,"observed_later_50":0}
           for name in ("BASELINE_5_TO_10","SAG30_SELECTED_UNDER_10")}
    eligible=0
    winners30=0
    winners50=0
    cases=[]
    for (session,symbol),samples in sorted(grouped.items()):
        # Open session incomplete -> must not enter finalized precision.
        if session > now_et.date().isoformat() or (
            session==now_et.date().isoformat() and now_et.hour<20):
            continue
        points=sorted(samples,key=lambda x:(x["retrieval_ts"],x["run_id"]))
        if not points:
            continue
        eligible+=1
        first30=next((i for i,x in enumerate(points) if float(x["change_pct"])>=30),None)
        first50=next((i for i,x in enumerate(points) if float(x["change_pct"])>=50),None)
        # An observed later target counts only when a timestamp is strictly later.
        winners30+=int(first30 is not None)
        winners50+=int(first50 is not None)
        rule_results={}
        for name in tally:
            candidates=[(i,x) for i,x in enumerate(points)
                        if -10 <= float(x["change_pct"]) < 10
                        and (5 <= float(x["change_pct"]) if name=="BASELINE_5_TO_10"
                             else int(x["selected"] or 0)==1)
                        and (first30 is None or i<first30)]
            if not candidates:
                continue
            idx,entry=candidates[0]
            future=[x for x in points[idx+1:]
                    if x["retrieval_ts"]>entry["retrieval_ts"]]
            hit30=next((x for x in future if float(x["change_pct"])>=30),None)
            hit50=next((x for x in future if float(x["change_pct"])>=50),None)
            tally[name]["alerts"]+=1
            tally[name]["observed_later_30"]+=int(hit30 is not None)
            tally[name]["observed_later_50"]+=int(hit50 is not None)
            rule_results[name]={"first_alert_ts":entry["retrieval_ts"],
                "first_alert_pct":entry["change_pct"],
                "later_observed_30":bool(hit30),"later_observed_50":bool(hit50),
                "first_30_ts":hit30["retrieval_ts"] if hit30 else None,
                "first_50_ts":hit50["retrieval_ts"] if hit50 else None}
        if rule_results:
            cases.append({"session":session,"symbol":symbol,
                          "rules":rule_results})
    for v in tally.values():
        v["precision_30_observed"]=v["observed_later_30"]/v["alerts"] if v["alerts"] else None
        v["precision_50_observed"]=v["observed_later_50"]/v["alerts"] if v["alerts"] else None
        v["winner_recall_30_observed"]=v["observed_later_30"]/winners30 if winners30 else None
        v["winner_recall_50_observed"]=v["observed_later_50"]/winners50 if winners50 else None
    return {"status":"MATCHED_RETROSPECTIVE_SHADOW_NOT_BUY",
            "denominator":"All finalized symbol-sessions in stored scout_history",
            "eligible_symbol_sessions":eligible,
            "winner_sessions_30":winners30,
            "winner_sessions_50":winners50,
            "rules":tally,
            "cases":cases,
            "limitations":"Retrospective descriptive test on same stored scout observations. Baseline 5-10% is not volume-confirmed; no quote/spread/fills or point-in-time data availability proof. Same cohort does not guarantee comparable alerts/day, and misses between snapshots remain unknown. No out-of-sample proof.",
            "no_real_buy":True}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    with sqlite3.connect(f"file:{a.db.resolve()}?mode=ro",uri=True) as db:
        rows=[dict(zip(("session","symbol","retrieval_ts","change_pct","selected","run_id"),row))
              for row in db.execute("SELECT session,symbol,retrieval_ts,change_pct,selected,run_id "
                                    "FROM scout_history ORDER BY session,symbol,retrieval_ts")]
    result=compare(rows)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="cases"},sort_keys=True))


if __name__=="__main__":
    main()
