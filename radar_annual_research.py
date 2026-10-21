"""One-year, survivorship-limited DAILY OHLCV research.

Daily bars cannot establish a within-minute entry, or backtest a 5-minute radar.
This module audits large-move frequency and next-session proxy outcomes only.
All thresholds are specified before replay; train/holdout split is temporal.
"""
import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from radar_historical_collector import COHORT

NY=ZoneInfo("America/New_York")
MAX_BYTES=900000
def fetch(symbol,opener=None):
    opener=opener or urllib.request.urlopen
    url=("https://query1.finance.yahoo.com/v8/finance/chart/"+
         urllib.parse.quote(symbol,safe="")+"?interval=1d&range=1y&events=div%2Csplits")
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with opener(req,timeout=9) as response:raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError("OVERSIZED")
    return json.loads(raw)

def parse(symbol,payload):
    try:
        data=payload["chart"]["result"][0]
        times=data["timestamp"]
        q=data["indicators"]["quote"][0]
        bars=[]
        for i,epoch in enumerate(times):
            raw=[q[k][i] for k in ("open","high","low","close","volume")]
            if any(v is None or isinstance(v,bool) for v in raw):continue
            o,h,l,c,v=[float(v) for v in raw]
            if not all(math.isfinite(x) for x in (o,h,l,c,v)):continue
            if not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):continue
            session=datetime.fromtimestamp(int(epoch),timezone.utc).astimezone(NY).date().isoformat()
            if bars and session<=bars[-1]["session"]:continue
            bars.append({"session":session,"open":o,"high":h,"low":l,"close":c,"volume":v})
        splits=data.get("events",{}).get("splits") or {}
        return bars,bool(splits)
    except (KeyError,IndexError,ValueError,TypeError,OverflowError,AttributeError):
        return [],False

def analyze_symbol(symbol,bars,has_splits=False):
    """Signals use a completed daily close; proxy entry is NEXT session OPEN.

    Avoid intraday lookahead and cross-stock same-day optimization.
    Split events are excluded because unadjusted comparisons may be distorted.
    """
    result={"symbol":symbol,"sessions":len(bars),"events":[],"eligible":False,
            "excluded_reason":None,"orders_enabled":False}
    if has_splits:
        result["excluded_reason"]="SPLIT_EVENT_IN_WINDOW"
        return result
    if len(bars)<180:
        result["excluded_reason"]="LESS_THAN_180_VALID_SESSIONS"
        return result
    result["eligible"]=True
    for i in range(21,len(bars)-6):
        prev=bars[i-1]
        day=bars[i]
        next_bar=bars[i+1]
        if prev["close"]<=0 or next_bar["open"]<=0:continue
        change=100*(day["close"]/prev["close"]-1)
        gap=100*(day["open"]/prev["close"]-1)
        past_volumes=[x["volume"] for x in bars[i-20:i]]
        avg_vol=sum(past_volumes)/len(past_volumes)
        rvol=day["volume"]/avg_vol if avg_vol>0 else None
        # Fixed daily categories. This CANNOT reconstruct the intraday +5-10 entry.
        if not (5<=change<=10 or change>=20 or gap>=10):continue
        entry=next_bar["open"]
        future=bars[i+1:i+6]
        future_peak=max(x["high"] for x in future)
        future_low=min(x["low"] for x in future)
        result["events"].append({
          "signal_date":day["session"],
          "signal_close":round(day["close"],5),
          "daily_change_pct":round(change,3),
          "daily_gap_pct":round(gap,3),
          "volume_ratio_20_prior_days":round(rvol,3) if rvol is not None else None,
          "group":"EARLY_DAILY_5_TO_10" if 5<=change<=10 else "GAP_OVER_10" if gap>=10 else "ALREADY_OVER_20",
          "proxy_entry_date":next_bar["session"],
          "outcome_last_session":future[-1]["session"],
          "proxy_entry_next_open":round(entry,5),
          "five_session_max_high_pct":round(100*(future_peak/entry-1),3),
          "five_session_min_low_pct":round(100*(future_low/entry-1),3),
          "hits_20_pct_upper_bound":future_peak>=entry*1.2,
          "valid_entry_fill":False,
          "granularity":"DAILY_NOT_INTRADAY"
        })
    return result

def summarize(items):
    all_events=[x for item in items for x in item["events"]]
    ordered=sorted(all_events,key=lambda x:x["signal_date"])
    dates=sorted({e["signal_date"] for e in ordered})
    if not dates:
        return {"status":"NO_ELIGIBLE_EVENTS","symbols_requested":len(items),
                "symbols_eligible":sum(x["eligible"] for x in items),"events":0,
                "data_granularity":"DAILY","orders_enabled":False}
    # Fixed calendar cut 2026-07-01, no random split or outcome-informed split.
    split="2026-07-01"
    def stats(group):
        hits=sum(x["hits_20_pct_upper_bound"] for x in group)
        return {"events":len(group),"hits_20":hits,
                "hit_rate_pct":round(100*hits/len(group),2) if group else None,
                "early_5_to_10_events":sum(x["group"]=="EARLY_DAILY_5_TO_10" for x in group)}
    years=[x["sessions"] for x in items if x["eligible"]]
    return {"status":"ANNUAL_DAILY_PROXY_RESEARCH",
       "source":"Yahoo 1d unofficial unadjusted bars","coverage_start":dates[0],
       "coverage_end":dates[-1],"symbols_requested":len(items),
       "symbols_eligible":sum(x["eligible"] for x in items),
       "symbols_excluded":[{"symbol":x["symbol"],"reason":x["excluded_reason"]} for x in items if not x["eligible"]],
       "minimum_valid_daily_bars":min(years) if years else None,
       "train_before":split,"holdout_from":split,
       "train":stats([x for x in ordered if x["signal_date"]<split]),
       "holdout":stats([x for x in ordered if x["signal_date"]>=split]),
       "by_group":{group:stats([x for x in ordered if x["group"]==group]) for group in
                   ("EARLY_DAILY_5_TO_10","GAP_OVER_10","ALREADY_OVER_20")},
       "events_total":len(ordered),
       "limitations":["Selected tickers are retrospective; no delisted universe or survivorship correction",
         "Daily entry is next OPEN, not actionable intraday discovery",
         "Forward highs are optimistic upper bounds; spreads, halts and fill not modeled",
         "No inference of prospective hit rate without point-in-time universe"],
       "intraday_validation_complete":False,"buy_enabled":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="annual-daily-research.json")
    args=p.parse_args()
    items=[]
    errors=[]
    for symbol in COHORT:
        try:
            bars,splits=parse(symbol,fetch(symbol))
            items.append(analyze_symbol(symbol,bars,splits))
        except Exception as exc:
            errors.append({"symbol":symbol,"error_type":type(exc).__name__})
            items.append({"symbol":symbol,"sessions":0,"events":[],"eligible":False,
                          "excluded_reason":"FETCH_FAILED","orders_enabled":False})
        time.sleep(.12)
    summary=summarize(items)
    summary["collection_errors"]=errors
    Path(args.out).write_text(json.dumps({"summary":summary,"symbols":items},indent=2)+"\n")
    print(json.dumps({k:summary.get(k) for k in
        ("status","coverage_start","coverage_end","symbols_eligible","events_total","train","holdout","collection_errors")}))
if __name__=="__main__":main()
