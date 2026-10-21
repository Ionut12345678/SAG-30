"""Retrospective intraday replay: no future information in entry features.

Requires real timestamped 5-minute OHLCV bars and previous session close.
This is research, not trading advice or evidence of executable fills.
"""
import argparse
import json
import math
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EASTERN=ZoneInfo("America/New_York")
TARGETS=(15,20,30,50)
def replay(symbol,bars,previous_close,*,horizon_minutes=390):
    """Replay one session; enter on first completed 5m bar closing +5..10% vs previous close.

    All entry-side features use bars before or at detection; subsequent outcomes
    use later bar highs/lows only. The earliest theoretical entry is next bar OPEN.
    """
    try:
        ref=float(previous_close)
        if not math.isfinite(ref) or ref<=0:raise ValueError()
        parsed=[]
        last=None
        for item in bars:
            ts=datetime.fromisoformat(item["ts"].replace("Z","+00:00"))
            if ts.tzinfo is None or (last is not None and ts<=last):raise ValueError()
            last=ts
            o,h,l,c,v=[float(item[k]) for k in ("open","high","low","close","volume")]
            if not all(math.isfinite(x) for x in (o,h,l,c,v)) or not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):raise ValueError()
            parsed.append((ts.astimezone(timezone.utc),o,h,l,c,v))
    except (TypeError,ValueError,KeyError,AttributeError,OverflowError):
        return {"symbol":symbol,"status":"INVALID_DATA"}
    if len(parsed)<4:return {"symbol":symbol,"status":"INSUFFICIENT_BARS"}
    entries=[i for i,b in enumerate(parsed[:-1]) if 5<=100*(b[4]/ref-1)<=10]
    if not entries:
        opening_pct=100*(parsed[0][4]/ref-1)
        peak_pct=100*(max(b[2] for b in parsed)/ref-1)
        return {"symbol":symbol,"status":"NO_EARLY_WINDOW",
                "first_regular_bar_change_pct":round(opening_pct,3),
                "session_peak_pct_vs_previous_close":round(peak_pct,3),
                "missed_20pct_runner":peak_pct>=20,
                "gap_above_10pct_at_first_bar":opening_pct>10,
                "interpretation":"MISSED_MOVE_NOT_ACTIONABLE_ENTRY",
                "orders_enabled":False}
    i=entries[0]
    signal=parsed[i]
    next_bar=parsed[i+1]
    signal_end=signal[0]  # data vendor bar START, bar completion 5min later
    entry_time=next_bar[0]
    if (entry_time-signal_end).total_seconds()<300:
        return {"symbol":symbol,"status":"INVALID_BAR_CADENCE"}
    # Conservative: next bar OPEN (not the signal's already-closed bar).
    entry_price=next_bar[1]
    prior=parsed[max(0,i-6):i]
    baseline_volume=sum(b[5] for b in prior)/len(prior) if prior else None
    volume_ratio=signal[5]/baseline_volume if baseline_volume and baseline_volume>0 else None
    observed=[b for b in parsed[i+1:] if 0<=(b[0]-entry_time).total_seconds()<=horizon_minutes*60]
    if not observed:return {"symbol":symbol,"status":"NO_FOLLOWUP"}
    max_high=max(x[2] for x in observed)
    min_low=min(x[3] for x in observed)
    hit={}
    for target in TARGETS:
        threshold=entry_price*(1+target/100)
        first=next((b for b in observed if b[2]>=threshold),None)
        if first:hit[str(target)]={"bar_start_utc":first[0].isoformat(),
                                   "minutes_since_entry":round((first[0]-entry_time).total_seconds()/60,1)}
    result={"symbol":symbol,"status":"EVALUATED_HISTORICAL_REPLAY",
        "previous_close":round(ref,5),"signal_bar_start_utc":signal_end.isoformat(),
        "signal_change_pct":round(100*(signal[4]/ref-1),3),
        "signal_close":signal[4],"entry_time_utc":entry_time.isoformat(),
        "proxy_entry_price_next_open":entry_price,
        "signal_volume_ratio_vs_prior_6":round(volume_ratio,3) if volume_ratio is not None else None,
        "peak_future_high":max_high,"min_future_low":min_low,
        "max_gain_from_proxy_entry_pct":round(100*(max_high/entry_price-1),3),
        "max_drawdown_from_proxy_entry_pct":round(100*(min_low/entry_price-1),3),
        "hits_from_proxy_entry":hit,
        "outcome":"WINNER_20" if "20" in hit else "FALSE_WINNER_UNDER_20",
        "quality":"HISTORICAL_BAR_REPLAY_UNVERIFIED_FILL_NO_SPREAD_OR_HALT",
        "orders_enabled":False}
    return result

def summarize(records):
    valid=[x for x in records if x.get("status")=="EVALUATED_HISTORICAL_REPLAY"]
    winners=[x for x in valid if x["outcome"]=="WINNER_20"]
    false_winners=[x for x in valid if x["outcome"]=="FALSE_WINNER_UNDER_20"]
    def median_volume_ratio(group):
        ratios=[x["signal_volume_ratio_vs_prior_6"] for x in group if x.get("signal_volume_ratio_vs_prior_6") is not None]
        return round(statistics.median(ratios),3) if ratios else None
    missed=[x for x in records if x.get("status")=="NO_EARLY_WINDOW"]
    return {"cases":len(records),"evaluated":len(valid),"excluded":len(records)-len(valid),
            "missed_20pct_runners_without_5to10_entry":sum(x.get("missed_20pct_runner",False) for x in missed),
            "first_bar_gaps_above_10pct":sum(x.get("gap_above_10pct_at_first_bar",False) for x in missed),
            "median_signal_volume_ratio_winner_20":median_volume_ratio(winners),
            "median_signal_volume_ratio_false_winner":median_volume_ratio(false_winners),
            "winner_20_count":sum(x["outcome"]=="WINNER_20" for x in valid),
            "false_winner_under_20_count":sum(x["outcome"]=="FALSE_WINNER_UNDER_20" for x in valid),
            "threshold_counts":{str(n):sum(str(n) in x["hits_from_proxy_entry"] for x in valid) for n in TARGETS},
            "sample_selection_bias_warning":"Historical candidate sampling is not a representative backtest without prespecified universe",
            "executable_return_verified":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True,help="JSON list: {symbol,previous_close,bars}")
    parser.add_argument("--out",default="historical-replay.json")
    args=parser.parse_args()
    data=json.loads(Path(args.input).read_text())
    if not isinstance(data,list):raise ValueError("Expected list")
    records=[replay(str(x.get("symbol","")),x.get("bars",[]),x.get("previous_close",0)) for x in data]
    report={"summary":summarize(records),"results":records}
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report["summary"]))
if __name__=="__main__":main()
