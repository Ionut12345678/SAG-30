"""Retrospective PREMARKET research without lookahead.

Five-minute Yahoo OHLCV bars, previous completed regular-session close.
Premarket entries are *theoretical* and may be impossible due to spread, halt,
order restrictions, and liquidity. No BUY and no real-time signal claims.
"""
import json
import math
from datetime import datetime, timezone, time as clock
from zoneinfo import ZoneInfo

NY=ZoneInfo("America/New_York")
def evaluate(symbol,previous_close,premarket,regular):
    try:
        ref=float(previous_close)
        if not math.isfinite(ref) or ref<=0:raise ValueError()
        bars=[]
        last=None
        for b in premarket:
            t=datetime.fromisoformat(b["ts"].replace("Z","+00:00"))
            if t.tzinfo is None or (last is not None and t<=last):raise ValueError()
            last=t
            o,h,l,c,v=[float(b[k]) for k in ("open","high","low","close","volume")]
            if not (0<l<=min(o,c)<=max(o,c)<=h and v>=0) or not all(math.isfinite(x) for x in (o,h,l,c,v)):raise ValueError()
            bars.append((t.astimezone(timezone.utc),o,h,l,c,v))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return {"symbol":symbol,"status":"INVALID_PREMARKET"}
    if len(bars)<3:
        return {"symbol":symbol,"status":"INSUFFICIENT_PREMARKET"}
    if 100*(bars[0][4]/ref-1)>10:
        return {"symbol":symbol,"status":"ALREADY_OVER_10_AT_FIRST_PREMARKET_BAR",
                "initial_premarket_pct":round(100*(bars[0][4]/ref-1),3)}
    # Fixed experimental watch band: first 5-min premarket close at +3..+10%.
    matches=[i for i,b in enumerate(bars[:-1]) if 3<=100*(b[4]/ref-1)<=10]
    if not matches:return {"symbol":symbol,"status":"NO_EARLY_PREMARKET_WINDOW"}
    i=matches[0]
    if i+1>=len(bars) or (bars[i+1][0]-bars[i][0]).total_seconds()!=300:
        return {"symbol":symbol,"status":"MISSING_ADJACENT_ENTRY_BAR"}
    signal=bars[i]
    nxt=bars[i+1]
    entry=nxt[1]
    earlier=bars[max(0,i-6):i]
    mean_volume=sum(b[5] for b in earlier)/len(earlier) if earlier else None
    volume_ratio=round(signal[5]/mean_volume,3) if mean_volume and mean_volume>0 else None
    # Bar opens and highs cannot be assumed executable.
    future_premarket=bars[i+1:]
    future_reg=[]
    for b in regular:
        try:
            t=datetime.fromisoformat(b["ts"].replace("Z","+00:00")).astimezone(timezone.utc)
            future_reg.append((t,float(b["high"])))
        except (ValueError,KeyError,TypeError,AttributeError):continue
    if not future_reg:return {"symbol":symbol,"status":"NO_REGULAR_FOLLOWUP"}
    peak_reg=max(h for _,h in future_reg)
    peak_pre=max(b[2] for b in future_premarket)
    threshold=entry*1.2
    return {"symbol":symbol,"status":"EVALUATED_PREMARKET_SHADOW",
            "signal_bar_start_utc":signal[0].isoformat(),
            "signal_pct_vs_previous_close":round(100*(signal[4]/ref-1),3),
            "signal_volume_ratio_vs_previous_6":volume_ratio,
            "proxy_entry_bar_start_utc":nxt[0].isoformat(),
            "proxy_entry_price":entry,
            "regular_session_peak":peak_reg,
            "peak_after_signal_pct":round(100*(max(peak_reg,peak_pre)/entry-1),3),
            "regular_session_peak_pct":round(100*(peak_reg/entry-1),3),
            "regular_hit_20":peak_reg>=threshold,
            "quality":"UNOFFICIAL_VENDOR_BARS_THEORETICAL_PREMARKET_ENTRY",
            "buy_enabled":False}

def extract(symbol,payload):
    try:
        data=payload["chart"]["result"][0]
        times=data["timestamp"]
        quotes=data["indicators"]["quote"][0]
        grouped={}
        for i,epoch in enumerate(times):
            t=datetime.fromtimestamp(int(epoch),timezone.utc)
            local=t.astimezone(NY)
            minute=local.time()
            if not clock(4,0)<=minute<clock(16,0):continue
            raw=[quotes[k][i] for k in ("open","high","low","close","volume")]
            if any(v is None for v in raw):continue
            o,h,l,c,v=[float(x) for x in raw]
            if not (0<l<=min(o,c)<=max(o,c)<=h and v>=0) or not all(math.isfinite(x) for x in (o,h,l,c,v)):continue
            kind="pre" if minute<clock(9,30) else "regular"
            grouped.setdefault(local.date().isoformat(),{"pre":[],"regular":[]})[kind].append(
                {"ts":t.isoformat(),"open":o,"high":h,"low":l,"close":c,"volume":v})
        out=[]
        dates=sorted(grouped)
        for i in range(1,len(dates)):
            prev=grouped[dates[i-1]]["regular"]
            today=grouped[dates[i]]
            if len(prev)<20 or len(today["regular"])<4:continue
            result=evaluate(symbol,prev[-1]["close"],today["pre"],today["regular"])
            result["session"]=dates[i]
            result["previous_session"]=dates[i-1]
            out.append(result)
        return out
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,AttributeError):
        return [{"symbol":symbol,"status":"INVALID_SOURCE_PAYLOAD"}]

def summarize(results):
    valid=[r for r in results if r.get("status")=="EVALUATED_PREMARKET_SHADOW"]
    return {"cases":len(results),"evaluated":len(valid),
            "regular_hit_20_count":sum(r["regular_hit_20"] for r in valid),
            "already_over_10_at_first_bar":sum(r.get("status")=="ALREADY_OVER_10_AT_FIRST_PREMARKET_BAR" for r in results),
            "insufficient_premarket":sum(r.get("status")=="INSUFFICIENT_PREMARKET" for r in results),
            "selection_is_retrospective":True,
            "fills_verified":False,"buy_enabled":False}
