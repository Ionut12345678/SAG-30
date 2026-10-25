"""Regime-conditioned historical diagnostics. Exploratory, NOT causal evidence.
No parameter optimization or real trading. Measurements use distinct forward
20-session samples per symbol to reduce dependence from overlapping horizons.
"""
import argparse,json,csv,math
from pathlib import Path
from statistics import mean
from backtest import load

def analyze(groups):
    results={}
    for period,start,end in (("train_2022_2023","2022-01-01","2023-12-31"),
                             ("validation_2024","2024-01-01","2024-12-31"),
                             ("holdout_2025_2026","2025-01-01","2026-12-31")):
        buckets={}
        for sym,bars in groups.items():
            for i in range(60,len(bars)-20,20):
                d=str(bars[i]["date"]);future_date=str(bars[i+20]["date"])
                if not(start<=d<=end and future_date<=end):continue
                px=bars[i]["close"]
                momentum=px/bars[i-20]["close"]-1
                ma20=mean(x["close"] for x in bars[i-19:i+1])
                ma60=mean(x["close"] for x in bars[i-59:i+1])
                changes=[math.log(bars[j]["close"]/bars[j-1]["close"]) for j in range(i-19,i+1)]
                avg=mean(changes)
                vol=math.sqrt(mean((v-avg)**2 for v in changes))*math.sqrt(252)
                oldvol=mean(b["volume"] for b in bars[i-20:i])
                volume_ratio=bars[i]["volume"]/oldvol if oldvol>0 else 0
                features={
                  "momentum_gt_5pct":momentum>.05,
                  "momentum_lt_minus_5pct":momentum<-.05,
                  "trend_above_ma20_ma60":px>ma20>ma60,
                  "downtrend_below_ma20_ma60":px<ma20<ma60,
                  "volume_spike_gt_1_5x":volume_ratio>1.5,
                  "volatility_gt_50pct":vol>.50,
                  "momentum_and_volume":momentum>.05 and volume_ratio>1.5,
                  "downtrend_and_high_vol":px<ma20<ma60 and vol>.50,
                  "all":True}
                forward=bars[i+20]["close"]/px-1
                for name,present in features.items():
                    if present:buckets.setdefault(name,[]).append(forward)
        results[period]={}
        for name,returns in sorted(buckets.items()):
            n=len(returns)
            results[period][name]={"n":n,"rise_pct":round(100*sum(r>0 for r in returns)/n,2),
                "fall_10pct_pct":round(100*sum(r<=-.10 for r in returns)/n,2),
                "gain_10pct_pct":round(100*sum(r>=.10 for r in returns)/n,2),
                "average_20day_return_pct":round(100*mean(returns),3)}
    return {"disclaimer":"Associations, not causes or executable P&L; fixed surviving symbols, no FX or macro/event controls. Holdout dates were previously explored and are not clean out-of-sample.", "periods":results}

def main():
    p=argparse.ArgumentParser();p.add_argument("csv");p.add_argument("--out",required=True);a=p.parse_args()
    groups=load(a.csv)
    volume={}
    with open(a.csv,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):volume[(row["symbol"],row["date"])]=float(row["volume"])
    for symbol,bars in groups.items():
        for b in bars:b["volume"]=volume[(symbol,str(b["date"]))]
    report=analyze(groups)
    Path(a.out).write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    for period,rows in report["periods"].items():
        print(period,json.dumps(rows))
if __name__=="__main__":main()
