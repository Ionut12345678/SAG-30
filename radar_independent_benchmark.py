"""Frozen hypothesis check on an independently sampled daily-bar archive.

This checks NEXT-DAY-OPEN proxy events only. It does NOT validate intraday
Radar Nou early discovery, tradable fills, or causal benefits of filters.
Thresholds are predeclared and evaluated without inspecting future outcomes.
"""
import argparse
import json
from pathlib import Path
from datetime import date

SPLIT="2026-01-01"
# Independent, fixed candidate filters. No fitting on the holdout data.
RULES={
    "baseline_all":lambda e: True,
    "early_5_to_10":lambda e:e["group"]=="EARLY_DAILY_5_TO_10",
    "early_rvol_1_5":lambda e:(e["group"]=="EARLY_DAILY_5_TO_10" and
                                    e["volume_ratio_20_prior_days"] is not None and
                                    e["volume_ratio_20_prior_days"]>=1.5),
    "gap_10_plus_rvol_2":lambda e:(e["daily_gap_pct"]>=10 and
                                    e["volume_ratio_20_prior_days"] is not None and
                                    e["volume_ratio_20_prior_days"]>=2),
    "close_20_plus_rvol_2":lambda e:(e["daily_change_pct"]>=20 and
                                    e["volume_ratio_20_prior_days"] is not None and
                                    e["volume_ratio_20_prior_days"]>=2),
}

def describe(events):
    n=len(events)
    winners=sum(e["hits_20_pct_upper_bound"] for e in events)
    drawdowns=[e["five_session_min_low_pct"] for e in events]
    return {"signals":n,"upper_bound_hit_20":winners,
            "upper_bound_hit_rate_pct":round(100*winners/n,2) if n else None,
            "worst_five_session_low_pct":round(min(drawdowns),3) if drawdowns else None,
            "count_lows_minus_10_or_worse":sum(x<=-10 for x in drawdowns),
            "risk_order_ambiguous":True}

def deoverlap(records):
    """Greedy earliest event per ticker, ignoring any next signal until first
    event's entire five-session outcome has concluded. Deterministic, no outcomes
    consulted when selecting an event.
    """
    selected=[]
    blocked_until={}
    for e in sorted(records,key=lambda x:(x["signal_date"],x["symbol"])):
        symbol=e["symbol"]
        signal=e["signal_date"]
        exit_date=e["outcome_last_session"]
        if not isinstance(signal,str) or not isinstance(exit_date,str):
            continue
        try:
            date.fromisoformat(signal)
            date.fromisoformat(exit_date)
        except ValueError:
            continue
        if exit_date<signal:continue
        if signal<=blocked_until.get(symbol,""):continue
        selected.append(e)
        blocked_until[symbol]=exit_date
    return selected

def compare(dataset):
    if not isinstance(dataset,dict):raise ValueError("expected archive object")
    results=dataset.get("symbols",[])
    records=[]
    for stock in results:
        if not isinstance(stock,dict) or not stock.get("eligible"):continue
        symbol=stock.get("symbol")
        if not isinstance(symbol,str) or not symbol:continue
        for event in stock.get("events",[]):
            if not isinstance(event,dict):continue
            required=("signal_date","outcome_last_session","group","daily_gap_pct",
                      "daily_change_pct","volume_ratio_20_prior_days",
                      "five_session_min_low_pct","hits_20_pct_upper_bound")
            if not all(k in event for k in required):continue
            records.append(dict(event,symbol=symbol))
    unique=deoverlap(records)
    # Purge train events whose forward windows touch holdout. This prevents
    # training labels from containing price action after the split.
    partitions={
      "train":[e for e in unique if e["outcome_last_session"]<SPLIT],
      "holdout":[e for e in unique if e["signal_date"]>=SPLIT]}
    purged=[e for e in unique if e["signal_date"]<SPLIT<=e["outcome_last_session"]]
    rows={}
    for period,events in partitions.items():
        baseline_wins=sum(bool(e["hits_20_pct_upper_bound"]) for e in events)
        rows[period]={}
        for name,rule in RULES.items():
            candidates=[e for e in events if rule(e)]
            stats=describe(candidates)
            stats["coverage_pct"]=round(100*len(candidates)/len(events),2) if events else None
            stats["winner_capture_pct"]=round(100*stats["upper_bound_hit_20"]/baseline_wins,2) if baseline_wins else None
            rows[period][name]=stats
    return {"status":"NONOVERLAPPING_FIXED_RULES_DAILY_PROXY",
            "split_date":SPLIT,"source":"independent archive (selected without winner labels)",
            "raw_event_count":len(records),"nonoverlapping_event_count":len(unique),
            "overlap_events_skipped":len(records)-len(unique),
            "cross_split_forward_windows_purged":len(purged),
            "train_signal_count":len(partitions["train"]),
            "holdout_signal_count":len(partitions["holdout"]),
            "event_count":len(records),"rule_count":len(RULES),"results":rows,
            "eligible_for_live_buy":False,"intraday_validated":False,
            "winning_rule_selected":False,
            "warning":"Earliest nonoverlapping events only. Optimistic bar highs, no fills/spreads/halts and no verified point-in-time universe.",
            "research_only":True}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default="independent-daily-sample.json")
    p.add_argument("--out",default="independent-pattern-benchmark.json")
    args=p.parse_args()
    raw=json.loads(Path(args.input).read_text())
    report=compare(raw)
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"status":report["status"],"event_count":report["event_count"],"overlap_events_skipped":report["overlap_events_skipped"],
                      "holdout":report["results"]["holdout"],"winning_rule_selected":False}))
if __name__=="__main__":main()
