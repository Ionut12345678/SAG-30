"""Shared-cash, long-only portfolio backtest. Daily bars, NO execution connectivity."""
import argparse, json
from collections import defaultdict
from pathlib import Path
from backtest import load, test_signal

def simulate(groups, initial=100., slots=2, allocation=20., fee_bps=10.,
             hold_days=10, stop=.05, start="2024-01-01"):
    dates=sorted(set.intersection(*(set(b["date"] for b in bars) for bars in groups.values())))
    lookup={s:{b["date"]:b for b in bars} for s,bars in groups.items()}
    indices={s:{b["date"]:i for i,b in enumerate(bars)} for s,bars in groups.items()}
    if not groups or not 0 < stop < 1 or hold_days < 1 or slots < 1 or allocation <= 0 or fee_bps < 0:\n        raise ValueError("Invalid portfolio settings")\n    cash=initial
    holdings={}
    trades=[]
    equity=[]\n    exposure=[]
    prev=None
    for d in dates:
        if d.isoformat()<start: continue
        # Orders decided after previous close; enter only at today's open.
        if prev is not None:
            # Exit held positions at today's open on stop gaps / max holding period.
            for s,p in list(holdings.items()):
                bar=lookup[s][d]
                if bar["open"] <= p["entry"]*(1-stop):
                    px=bar["open"]; reason="gap_stop"
                elif p["age"] >= hold_days - 1:
                    px=bar["open"]; reason="horizon"
                else:
                    continue
                proceeds=p["qty"]*px*(1-fee_bps/10000)
                cash+=proceeds
                trades.append({"symbol":s,"entry_date":p["date"],"exit_date":str(d),
                               "pnl":round(proceeds-p["spent"],5),"reason":reason})
                del holdings[s]
            # Rank by 20-day momentum at previous close; no lookahead.
            candidates=[]
            for s,bars in groups.items():
                i=indices[s].get(prev)
                if i is None or i < 60 or s in holdings or not test_signal(bars,i):continue
                score=bars[i]["close"]/bars[i-20]["close"]-1
                candidates.append((score,s))
            for _,s in sorted(candidates,reverse=True):
                if len(holdings)>=slots:break
                stake=min(allocation,cash)
                if stake<allocation:break
                px=lookup[s][d]["open"]
                fee=stake*fee_bps/10000
                qty=(stake-fee)/px
                holdings[s]={"entry":px,"qty":qty,"spent":stake,"date":str(d),"age":0}
                cash-=stake
        # OHLC cannot resolve entry-open versus later intraday stop ordering.\n        # Since entry is at the opening auction, a subsequent low at/below stop\n        # is conservatively assumed to trigger even on entry day.
        for s,p in list(holdings.items()):
            bar=lookup[s][d]
            if bar["low"] <= p["entry"]*(1-stop):
                px=p["entry"]*(1-stop)
                proceeds=p["qty"]*px*(1-fee_bps/10000)
                cash+=proceeds
                trades.append({"symbol":s,"entry_date":p["date"],"exit_date":str(d),
                               "pnl":round(proceeds-p["spent"],5),"reason":"stop"})
                del holdings[s]
            elif p["date"] != str(d):
                p["age"]+=1
        value=cash+sum(p["qty"]*lookup[s][d]["close"] for s,p in holdings.items())
        equity.append({"date":str(d),"equity":round(value,5)})\n        exposure.append(sum(p["qty"]*lookup[s][d]["close"] for s,p in holdings.items())/value if value>0 else 0)
        prev=d
    if not equity:raise ValueError("No synchronized dates")
    last=equity[-1]["date"]
    final=equity[-1]["equity"]
    peak=initial; worst=0.
    for r in equity:
        peak=max(peak,r["equity"])
        worst=min(worst,r["equity"]/peak-1)
    return {"start":equity[0]["date"],"end":last,"initial":initial,
            "final_mark_to_market":final,"net_return_pct":round(100*(final/initial-1),4),
            "max_drawdown_pct":round(100*worst,4),"closed_trades":len(trades),
            "open_positions":list(holdings),"average_exposure_pct":round(100*sum(exposure)/len(exposure),3),\n            "monthly_return_pct":monthly(equity),
            "trades":trades}

def monthly(equity):
    ends={}
    for item in equity:ends[item["date"][:7]]=item["equity"]
    prior=equity[0]["equity"]
    result={}
    for month,value in sorted(ends.items()):
        result[month]=round(100*(value/prior-1),4)
        prior=value
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--out",required=True)
    p.add_argument("--start",default="2024-01-01")
    a=p.parse_args()
    data=load(a.csv)
    result=simulate(data,start=a.start)
    Path(a.out).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="trades"},indent=2))
if __name__=="__main__":
    main()
