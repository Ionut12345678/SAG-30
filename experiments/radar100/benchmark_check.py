"""Equal-exposure reference and preselected filter report for Radar100; research only."""
import argparse,csv,json
from pathlib import Path
from statistics import mean
from backtest import load
from filter_portfolio import enrich,select_signal
import portfolio

def benchmark(groups,start,capital=100.,max_exposure=40.,fee_bps=10.):
    dates=sorted(set.intersection(*(set(b["date"] for b in bars) for bars in groups.values())))
    dates=[d for d in dates if str(d)>=start]
    if len(dates)<2:raise ValueError("Insufficient dates")
    lookup={s:{b["date"]:b for b in bars} for s,bars in groups.items()}
    first,last=dates[0],dates[-1]
    names=sorted(groups)
    amount=max_exposure/len(names)
    # Remaining capital stays as zero-interest cash. Buy first synchronized day.
    cost=amount*fee_bps/10000
    shares={s:(amount-cost)/lookup[s][first]["open"] for s in names}
    equity=[]
    for d in dates:
        value=capital-max_exposure+sum(shares[s]*lookup[s][d]["close"] for s in names)
        equity.append(value)
    peak=capital;dd=0
    for v in equity:
        peak=max(peak,v)
        dd=min(dd,v/peak-1)
    return {"return_pct":round((equity[-1]/capital-1)*100,4),
            "drawdown_pct":round(dd*100,4),"exposure_pct_initial":40,
            "limitation":"Static initial exposure, not dynamic exposure-matched: radar positions vary."}

def main():
    p=argparse.ArgumentParser();p.add_argument("csv");p.add_argument("--out",required=True);a=p.parse_args()
    groups=load(a.csv);enrich(a.csv,groups)
    result=[]
    original=portfolio.test_signal
    try:
        for start in ("2024-01-01","2025-01-01","2026-01-01"):
            row={"start":start,"benchmark":benchmark(groups,start)}
            for name in ("baseline","momentum","trend_volume"):
                portfolio.test_signal=lambda bars,i,k=name:select_signal(bars,i,k)
                r=portfolio.simulate(groups,start=start)
                row[name]={"return_pct":r["net_return_pct"],"drawdown_pct":r["max_drawdown_pct"],
                           "closed_trades":r["closed_trades"]}
            result.append(row)
    finally:portfolio.test_signal=original
    Path(a.out).write_text(json.dumps({"comparisons":result,
      "limitations":"Exploratory reused historical periods, 21 survivors, USD priced as EUR, static versus dynamic exposure, no taxes/FX. This is not independent holdout or matched-risk evidence."},indent=2)+"\n")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
