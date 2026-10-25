"""Scenario matrix over historical bars. Research only; no broker connection.
Scores are out-of-sample when evaluated on 2025+, with fixed predeclared rules.
"""
import argparse, json
from datetime import date
from pathlib import Path
from portfolio import simulate
from backtest import load

def benchmark(groups, start, cash=100.):
    # Equal-weight buy-and-hold, purchases at first common trading day's open.
    common=sorted(set.intersection(*(set(b["date"] for b in rows) for rows in groups.values())))
    common=[d for d in common if str(d)>=start]
    if len(common)<2: raise ValueError("Not enough common dates")
    symbols=sorted(groups)
    lookup={s:{bar["date"]:bar for bar in rows} for s,rows in groups.items()}
    invested=sum((cash/len(symbols))/lookup[s][common[0]]["open"]*lookup[s][common[-1]]["close"] for s in symbols)
    return round(100*(invested/cash-1),3)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--out",required=True)
    a=p.parse_args()
    data=load(a.csv)
    scenarios=[]
    for start in ("2024-01-01","2025-01-01","2026-01-01"):
        baseline=benchmark(data,start)
        for slots,allocation,stop,hold,fees in [
            (1,20,.05,10,10),(2,20,.05,10,10),
            (3,20,.05,10,10),(2,10,.05,10,10),
            (2,20,.03,10,10),(2,20,.08,10,10),
            (2,20,.05,5,10),(2,20,.05,20,10),
            (2,20,.05,10,30)]:
            r=simulate(data,start=start,slots=slots,allocation=allocation,
                       stop=stop,hold_days=hold,fee_bps=fees)
            months=r["monthly_return_pct"]
            scenarios.append({"start":start,"slots":slots,"allocation":allocation,
              "stop_pct":stop*100,"hold_days":hold,"fee_bps":fees,
              "return_pct":r["net_return_pct"],"drawdown_pct":r["max_drawdown_pct"],
              "trades":r["closed_trades"],"months_ge_10pct":sum(v>=10 for v in months.values()),
              "months_observed":len(months),"equal_weight_buy_hold_pct":baseline})
    result={"warning":"Exploratory grid, not optimizer or validated holdout; benchmark ignores commissions/dividends/FX, while adjusted prices may already incorporate dividend adjustments. No DCA or leverage in portfolio engine.","scenarios":scenarios}
    Path(a.out).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    for r in scenarios:print(json.dumps(r))
if __name__=="__main__":main()
