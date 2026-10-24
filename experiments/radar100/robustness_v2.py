"""Robustness diagnostics for predefined Momentum and Trend+Volume rules.
Exclude one ticker at a time to expose concentration/survivorship sensitivity.
Historical exploratory study, not a true future holdout or production signal.
"""
import argparse,json
from pathlib import Path
from backtest import load
from filter_portfolio import enrich,select_signal
import portfolio

def run(groups,signal,fee,period):
    prior=portfolio.test_signal
    try:
        portfolio.test_signal=lambda bars,i:select_signal(bars,i,signal)
        r=portfolio.simulate(groups,start=period,fee_bps=fee)
        return {k:r[k] for k in ("net_return_pct","max_drawdown_pct","closed_trades","average_exposure_pct")}
    finally:
        portfolio.test_signal=prior

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    groups=load(args.csv)
    enrich(args.csv,groups)
    names=sorted(groups)
    report={"ticker_count":len(names),"period":"2026-01-01 onward",
            "warnings":["Fixed current stock universe suffers survivorship/selection bias.",
                        "USD positions simulated without real EUR FX or real broker costs.",
                        "Multiple historical experiments have already examined this period.",
                        "Leave-one-out sensitivity is NOT out-of-sample future validation."],
            "strategies":{}}
    for strategy in ("baseline","momentum","trend_volume"):
        standard=run(groups,strategy,10,"2026-01-01")
        expensive=run(groups,strategy,50,"2026-01-01")
        exclusions=[]
        for excluded in names:
            sub={s:bars for s,bars in groups.items() if s!=excluded}
            r=run(sub,strategy,10,"2026-01-01")
            exclusions.append({"excluded":excluded,**r})
        report["strategies"][strategy]={
            "standard_10bps":standard,"stress_50bps":expensive,
            "leave_one_out_min_pct":min(row["net_return_pct"] for row in exclusions),
            "leave_one_out_max_pct":max(row["net_return_pct"] for row in exclusions),
            "leave_one_out_positive_count":sum(row["net_return_pct"]>0 for row in exclusions),
            "leave_one_out":exclusions}
        print(strategy, "base",standard["net_return_pct"],"50bps",expensive["net_return_pct"],
              "leave-one-out range",report["strategies"][strategy]["leave_one_out_min_pct"],
              report["strategies"][strategy]["leave_one_out_max_pct"])
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":
    main()
