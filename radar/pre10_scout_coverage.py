"""Source-limited investigation of pre-10% scout coverage for observed winners.

Does not infer prices in unobserved intervals or feed trading decisions.
"""
import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


def parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def audit(db_path, winner_report):
    with sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True) as con:
        columns={r[1] for r in con.execute("PRAGMA table_info(scout_history)")}
        required={"session","symbol","retrieval_ts","change_pct","selected"}
        if not required <= columns:
            raise ValueError("SCOUT_HISTORY_SCHEMA_INCOMPLETE")
        cases=[]
        for w in winner_report["winners"]:
            rows=con.execute("""SELECT retrieval_ts,change_pct,selected FROM scout_history
                 WHERE session=? AND symbol=? ORDER BY retrieval_ts""",
                 (w["session"],w["symbol"])).fetchall()
            first30=parse(w["first_30_ts"])
            if first30 is None:
                raise ValueError("INVALID_WINNER_TARGET_TS")
            prior=[(parse(ts),float(p),int(sel or 0)) for ts,p,sel in rows
                   if parse(ts) is not None and parse(ts)<first30 and p is not None]
            below10=[x for x in prior if x[1]<10]
            if below10:
                verdict="PRE10_SCOUT_OBSERVED"
            elif prior:
                verdict="FIRST_AVAILABLE_PRE30_ALREADY_GE10"
            else:
                verdict="NO_SCOUT_SAMPLE_BEFORE_30"
            earliest=prior[0] if prior else None
            cases.append({"session":w["session"],"symbol":w["symbol"],
                "classification":w["classification_under_10"],"coverage_verdict":verdict,
                "first_30_ts":w["first_30_ts"],"first_pre30_retrieval_ts":earliest[0].isoformat() if earliest else None,
                "first_pre30_change_pct":earliest[1] if earliest else None,
                "pre30_scout_rows":len(prior),"pre10_scout_rows":len(below10),
                "pre10_selected_rows":sum(x[2]==1 for x in below10),
                "provider_cause":"UNKNOWN_WITHOUT_SOURCE_TIMESTAMP_AND_FEED_COVERAGE",
                "actionable":"UNKNOWN_NO_BID_ASK_EXECUTION_PROOF"})
    counts=Counter(x["coverage_verdict"] for x in cases)
    miss=[x for x in cases if x["classification"]=="SCOUT_MISS"]
    return {"status":"RETROSPECTIVE_READONLY_COVERAGE_DIAGNOSTIC",
            "winner_sessions":len(cases),"scout_miss_sessions":len(miss),
            "all_coverage_counts":dict(counts),
            "scout_miss_coverage_counts":dict(Counter(x["coverage_verdict"] for x in miss)),
            "limitations":"Only retained retrieval snapshots; cannot distinguish absent bars, late discovery, and data provider failure. Does not reconstruct missing earlier prices.",
            "cases":cases,"buy":False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--winners",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    report=audit(a.db,json.loads(a.winners.read_text()))
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="cases"},sort_keys=True))


if __name__=="__main__":
    main()
