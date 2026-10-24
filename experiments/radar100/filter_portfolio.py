"""Shared-cash filter comparison: uses existing portfolio engine, fixed historical rules."""
import argparse,csv,json
from pathlib import Path
from statistics import mean
from backtest import load
from portfolio import simulate

def enrich(path,groups):
    volume={}
    with open(path,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            volume[(row["symbol"],row["date"])]=float(row["volume"])
    for symbol,bars in groups.items():
        for b in bars:b["volume"]=volume[(symbol,str(b["date"]))]

def select_signal(bars,i,kind):
    if i<60:return False
    c=bars[i]["close"]
    ma20=mean(x["close"] for x in bars[i-19:i+1])
    ma60=mean(x["close"] for x in bars[i-59:i+1])
    momentum=c/bars[i-20]["close"]-1
    returns=[bars[j]["close"]/bars[j-1]["close"]-1 for j in range(i-19,i+1)]
    avg=mean(returns)
    vol=(mean((r-avg)**2 for r in returns)**.5)*252**.5
    oldvol=mean(x["volume"] for x in bars[i-20:i])
    highvol=oldvol>0 and bars[i]["volume"]>1.5*oldvol
    filters={"baseline":c>ma20>ma60 and momentum>=.03,
             "trend":c>ma20>ma60,
             "momentum":momentum>.05,
             "low_vol":vol<.35,
             "high_volume":highvol,
             "trend_low_vol":c>ma20>ma60 and vol<.35,
             "trend_volume":c>ma20>ma60 and highvol}
    return filters[kind]

def main():
    p=argparse.ArgumentParser();p.add_argument("csv");p.add_argument("--out",required=True);a=p.parse_args()
    groups=load(a.csv);enrich(a.csv,groups)
    import portfolio
    original=portfolio.test_signal
    out=[]
    try:
        for period in ("2024-01-01","2025-01-01","2026-01-01"):
            for kind in ("baseline","trend","momentum","low_vol","high_volume","trend_low_vol","trend_volume"):
                portfolio.test_signal=lambda bars,i,k=kind:select_signal(bars,i,k)
                r=simulate(groups,start=period)
                out.append({"start":period,"filter":kind,"return_pct":r["net_return_pct"],
                            "max_drawdown_pct":r["max_drawdown_pct"],"trades":r["closed_trades"],
                            "months_ge_10":sum(v>=10 for v in r["monthly_return_pct"].values())})
    finally:portfolio.test_signal=original
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    for x in out:print(json.dumps(x))
if __name__=="__main__":main()
