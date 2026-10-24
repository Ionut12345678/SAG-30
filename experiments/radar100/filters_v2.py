"""Predeclared filter diagnostics. Forward close-to-close research, not executable P&L."""
import argparse,json,math
from statistics import mean
from pathlib import Path
from backtest import load

FILTERS=("all","trend","low_vol","high_volume","momentum","trend_low_vol","trend_volume")
def calc(groups,start,end,horizon=10):
    totals={name:[] for name in FILTERS}
    base=[]
    for symbol,bars in groups.items():
        for i in range(60,len(bars)-horizon):
            d=str(bars[i]["date"]); end_date=str(bars[i+horizon]["date"])
            if not(start<=d<=end and end_date<=end):continue
            close=bars[i]["close"]
            past=[b["close"] for b in bars[i-20:i+1]]
            returns=[math.log(past[j]/past[j-1]) for j in range(1,len(past))]
            mu=mean(returns)
            vol=math.sqrt(mean((z-mu)**2 for z in returns))*math.sqrt(252)
            bars20=bars[i-20:i]
            volumes=[x.get("volume",0) for x in bars20]
            # backtest.load currently drops volume; use raw CSV parser in this module instead.
            trend=close>mean(b["close"] for b in bars[i-19:i+1])>mean(b["close"] for b in bars[i-59:i+1])
            mom=close/bars[i-20]["close"]-1
            labels={"all":True,"trend":trend,"low_vol":vol<.35,"high_volume":False,
                    "momentum":mom>.05,"trend_low_vol":trend and vol<.35,"trend_volume":False}
            y=bars[i+horizon]["close"]/close-1
            base.append(y)
            for name,ok in labels.items():
                if ok:totals[name].append(y)
    def metric(xs):
        if not xs:return {"n":0,"direction_up_pct":None,"mean_forward_pct":None}
        return {"n":len(xs),"direction_up_pct":round(100*sum(x>0 for x in xs)/len(xs),3),
                "mean_forward_pct":round(100*mean(xs),3)}
    return {name:metric(vals) for name,vals in totals.items()}

def main():
    p=argparse.ArgumentParser();p.add_argument("csv");p.add_argument("--out",required=True);a=p.parse_args()
    # Explicit volume restoration from input, no changing shared backtest API.
    groups=load(a.csv)
    import csv
    volume={}
    with open(a.csv,newline="",encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            volume[(r["symbol"],r["date"])]=float(r["volume"])
    for symbol,bars in groups.items():
        for b in bars:b["volume"]=volume[(symbol,str(b["date"]))]
    # Volume flags inserted into local rules by using a separate wrapper.
    out={}
    for name,start,end in (("validation","2024-01-01","2024-12-31"),("test","2025-01-01","2026-12-31")):
        out[name]=calc_with_volume(groups,start,end)
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,indent=2))

def calc_with_volume(groups,start,end,horizon=10):
    selected={k:[] for k in FILTERS}
    for bars in groups.values():
        for i in range(60,len(bars)-horizon):
            d=str(bars[i]["date"]); ed=str(bars[i+horizon]["date"])
            if not(start<=d<=end and ed<=end):continue
            close=bars[i]["close"]
            r=[math.log(bars[j]["close"]/bars[j-1]["close"]) for j in range(i-19,i+1)]
            mu=mean(r);vol=(mean((v-mu)**2 for v in r)**.5)*252**.5
            trend=close>mean(b["close"] for b in bars[i-19:i+1])>mean(b["close"] for b in bars[i-59:i+1])
            mom=close/bars[i-20]["close"]-1
            avg_vol=mean(b["volume"] for b in bars[i-20:i])
            volume=avg_vol>0 and bars[i]["volume"]>1.5*avg_vol
            flags={"all":True,"trend":trend,"low_vol":vol<.35,"high_volume":volume,
                   "momentum":mom>.05,"trend_low_vol":trend and vol<.35,"trend_volume":trend and volume}
            future=bars[i+horizon]["close"]/close-1
            for name,active in flags.items():
                if active:selected[name].append(future)
    def report(v):
        if not v:return {"n":0,"up_pct":None,"avg_forward_pct":None}
        return {"n":len(v),"up_pct":round(100*sum(x>0 for x in v)/len(v),3),
                "avg_forward_pct":round(100*mean(v),3)}
    return {k:report(v) for k,v in selected.items()}
if __name__=="__main__":main()
