# Radar100 — isolated research prototype

**Not production-ready.** No real trades, no leverage, no broker tokens, no scheduled jobs. Does not change SAG-30 FROZEN, SAG-Crypto, PR #71, or existing workflows.

## Purpose
Backtest a simple long-only momentum screen for a hypothetical **100 EUR** account. An aspirational +10%/month is **not** a prediction or a required trading quota.

## Run
Supply historical adjusted daily OHLC bars in UTF-8 CSV, columns:
`symbol,date,open,high,low,close` (ISO YYYY-MM-DD). No dataset is included; results must never be described as verified until data quality, splits, delistings, and symbol coverage are audited.

```bash
python experiments/radar100/backtest.py prices.csv --symbol NVDA --out /tmp/radar100.json
python experiments/radar100/backtest.py prices.csv --symbol NVDA --dca
cd experiments/radar100 && python -m unittest -v test_backtest.py
```

## Research specification
- Signals use **only bars up to close at t**, entry at **open of t+1**, standard 20/60 trading-day trend + 20-day momentum threshold.
- One position at a time *per symbol*; test 10-bar horizon, 5% entry stop, max 20 EUR notional per simulated position, 10 bps cost each side. DCA optional, with 50/30/20 percent allocations at first entry / 3% / 6% below first entry, total exposure capped at 20 EUR.
- Stops are filled at stop threshold when touched, but at worse next opening prices for gaps. Same-day stop takes precedence over hypothetical DCA fills. Not a tick-accurate intraday simulator.
- Run chronological train/validation/test or walk-forward, and use survivorship-bias-free symbol universe. Compare with buy-and-hold; log all signals, no cherry-picking.
- **No leverage** until independent out-of-sample and paper-trading evidence, including funding, slippage, liquidation scenarios and drawdowns.

## Limitations / blockers to address
1. This is a **single-symbol isolated prototype**: running it separately on many tickers does NOT form a coherent shared-cash multi-symbol portfolio or enforce a real daily/monthly risk limit.
2. The daily OHLC source and adjusted/open-close consistency must be verified (especially dividend/split adjustment); delisted assets matter.
3. Data availability, exchange calendars, gaps, market impact, minimum broker order size, fractional shares, taxes, FX and financing are not modeled.
4. Portfolio equity/drawdown, risk-based sizing, chronological allocation across symbols, probabilistic forecast calibration and live/paper execution integration **not implemented**.
5. Research cannot assume +10% monthly. Real-money deployment blocked pending independent validation.

## Acceptance gates
- Minimum 3–5 years of inspected historical data where available; temporal out-of-sample testing.
- At least 100 paper trades, 3+ months forward observation, realistic costs.
- Demonstrated positive net expectancy and improved risk-adjusted outcome versus a relevant passive benchmark.
- No real orders or leverage without a **separate explicit authorization**.
