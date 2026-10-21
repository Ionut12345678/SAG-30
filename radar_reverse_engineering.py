"""Offline reverse engineering of historical +30/+50% runners, no orders or live alerts.

Input JSON: [{"symbol":"XYZ","bars":[{"ts":"2026-10-19T14:30:00Z",
"price":10.0,"volume":1000}, ...]}]. Bars must be chronological and independently
sourced; the caller is responsible for provenance and licensing.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

def evaluate(symbol, bars, levels=(15,20,30,50)):
    if len(bars)<3:
        return {"symbol":symbol,"status":"INSUFFICIENT_BARS"}
    previous=None
    parsed=[]
    for bar in bars:
        try:
            ts=datetime.fromisoformat(bar["ts"].replace("Z","+00:00"))
            price=float(bar["price"])
            volume=float(bar["volume"])
        except (KeyError,TypeError,ValueError,AttributeError):
            return {"symbol":symbol,"status":"INVALID_BAR"}
        if ts.tzinfo is None or price<=0 or volume<0 or (previous is not None and ts<=previous):
            return {"symbol":symbol,"status":"INVALID_SEQUENCE"}
        previous=ts
        parsed.append((ts,price,volume))
    reference=parsed[0][1]
    entry=next((i for i,(_,p,_) in enumerate(parsed[1:],1) if 5<=100*(p/reference-1)<=10),None)
    if entry is None:
        return {"symbol":symbol,"status":"NO_5_TO_10_ENTRY"}
    start=parsed[entry]
    after=parsed[entry+1:]
    if not after:
        return {"symbol":symbol,"status":"NO_LATER_BARS"}
    peak=max(after,key=lambda x:x[1])
    reached={}
    for level in levels:
        hit=next((b for b in after if 100*(b[1]/reference-1)>=level),None)
        if hit is not None:
            reached[str(level)]={"ts":hit[0].isoformat(),"pct_vs_reference":round(100*(hit[1]/reference-1),3),
                                 "pct_from_entry":round(100*(hit[1]/start[1]-1),3)}
    prior=parsed[max(0,entry-3):entry]
    avg_volume=sum(b[2] for b in prior)/len(prior) if prior else 0
    return {"symbol":symbol,"status":"HISTORICAL_EVALUATED",
            "entry_ts":start[0].isoformat(),"entry_pct_vs_reference":round(100*(start[1]/reference-1),3),
            "entry_price":start[1],"entry_volume_ratio":round(start[2]/avg_volume,3) if avg_volume else None,
            "peak_ts":peak[0].isoformat(),"peak_pct_vs_reference":round(100*(peak[1]/reference-1),3),
            "peak_pct_from_entry":round(100*(peak[1]/start[1]-1),3),
            "thresholds":reached,"bars_after_entry":len(after),
            "quality":"HISTORICAL_BAR_BACKTEST_NOT_EXECUTABLE_PROOF"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",default="reverse-engineering-report.json")
    args=p.parse_args()
    cases=json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(cases,list):
        raise ValueError("Expected a list of cases")
    results=[evaluate(str(c.get("symbol","")),c.get("bars",[])) for c in cases]
    evaluated=[r for r in results if r["status"]=="HISTORICAL_EVALUATED"]
    summary={"cases":len(results),"evaluated":len(evaluated),
             "rejected":len(results)-len(evaluated),
             "hits_from_first_5_to_10_observation":{},
             "false_winners_no_15pct":sum(not r["thresholds"].get("15") for r in evaluated)}
    for level in (15,20,30,50):
        count=sum(str(level) in r["thresholds"] for r in evaluated)
        summary["hits_from_first_5_to_10_observation"][str(level)]={
            "count":count,"rate_pct":round(100*count/len(evaluated),2) if evaluated else None}
    Path(args.output).write_text(json.dumps({"results":results,"summary":summary},indent=2)+"\\n",encoding="utf-8")
    print(json.dumps({"cases":len(results),"evaluated":sum(r["status"]=="HISTORICAL_EVALUATED" for r in results)}))
if __name__=="__main__":
    main()
