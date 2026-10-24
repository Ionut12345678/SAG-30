"""Multi-symbol research report: independent per-symbol experiments, NOT portfolio P&L."""
import argparse
import csv
import json
from pathlib import Path
from backtest import load, backtest

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--out",required=True)
    a=p.parse_args()
    groups=load(a.csv)
    results=[]
    for sym,bars in sorted(groups.items()):
        if len(bars)<250:
            raise ValueError(f"{sym}: insufficient history")
        for mode in (False,True):
            r=backtest(bars,dca=mode)
            trades=r["trades"]
            gross_win=sum(max(0,t["pnl_eur"]) for t in trades)
            gross_loss=-sum(min(0,t["pnl_eur"]) for t in trades)
            results.append({"symbol":sym,"strategy":"DCA" if mode else "single",
                 "bars":len(bars),"start":str(bars[0]["date"]),"end":str(bars[-1]["date"]),
                 "trades":r["trade_count"],"wins":r["wins"],
                 "net_return_pct":r["net_return_pct"],
                 "profit_factor":round(gross_win/gross_loss,3) if gross_loss else None,
                 "yearly_pnl_eur":{year:round(sum(t["pnl_eur"] for t in trades if t["exit_date"].startswith(year)),3)
                    for year in sorted({t["exit_date"][:4] for t in trades})},
                 "status":"research_only"})
    payload={"method":"independent, sequential, fixed-notional single-stock simulations",
      "warning":"Returns cannot be summed or interpreted as shared-cash portfolio; USD-to-EUR, taxes, delistings, and risk-adjusted portfolio comparison not modeled.",
      "results":results}
    dest=Path(a.out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    for r in results:
        print(f'{r["symbol"]:5} {r["strategy"]:6} n={r["trades"]:3} result={r["net_return_pct"]:8.3f}% PF={r["profit_factor"]}')
if __name__=="__main__":
    main()
