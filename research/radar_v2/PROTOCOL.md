# Radar v2 — research-only, independent of prospective SAG-30
Date: 2026-10-26. Status: design/protocol, **not a completed backtest**.

## Immutable boundaries
- No changes to SAG-30 v0.3.3 FROZEN, PR #71, SAG-Crypto, existing workflows, orders or production scanners.
- No BUY, no merge, no scheduler, no writes to production state.
- Existing prospective evaluation (2026-10-21 through 2026-11-20) stays separate; no replay/historical events can enter its ledger.

## Research question
Among US-listed equities that first reach +3% to +10% relative to the **prior regular-session adjusted close**, which *information available at the observation timestamp* predicts subsequent achievement of +15/+20/+30/+50% relative to that same reference? Compare to matched non-breakout controls and a pre-breakout (<+3%) cohort.

## Dataset and anti-leakage protocol
1. Obtain at least 12 months of point-in-time timestamped intraday OHLCV (prefer 1- or 5-minute bars), adjusted corporate actions, delisted tickers, exchange calendar and historical shares outstanding/float if available. Do not claim 12-month study until licensed/accessible dataset is confirmed.
2. Include NYSE/Nasdaq/NYSE American and delisted symbols, with liquidity and price strata. Do not select only future winners (survivorship/selection bias).
3. Each day's reference is the prior **regular-session** close, with corporate action adjustment. Tag premarket, regular and after-hours distinctly.
4. First eligible detection = earliest actual scan timestamp when a contemporaneously available quote in [+3%, +10%] passes freshness checks; if only OHLC bars are available, timestamp at bar close and explicitly model detection latency. Never backdate to intrabar high or news publication before ingest.
5. For each detection store symbol, first_seen_utc, session, provider, source_timestamp_utc, ingested_at_utc, observed_price, prior_regular_close, observed_volume, rolling volume baseline, corporate action version, freshness, validation flags, raw record checksum.
6. Keep DISCOVERED_RAW and VALIDATED_SIGNAL separate. Reject stale/duplicate/out-of-order quotes; preserve rejected rows and reason. One quote event is unique by (provider,symbol,source_timestamp,price,volume).
7. Features must be timestamp-causal: relative volume vs same time of day, 5/15/30-minute price acceleration, dollar volume, spread where available, market/sector returns, gap, volatility, news/earnings/SEC catalyst known by ingest timestamp, float when point-in-time available. Missing features stay missing.
8. Track only subsequent timestamped quotes (strictly > first_seen) for first touches of +15/+20/+30/+50% relative to prior regular close; record touch timestamp, elapsed time and worst drawdown; never use highs from before discovery.
9. Evaluate at fixed 1h, end-of-session, 1d, 5d and 20d horizons with censoring and explicit unobserved outcomes. No assumptions about fills or profitability.
10. Split chronologically: train first 60%, validation next 20%, untouched test last 20%; purge overlapping event horizons and embargo. Freeze features/thresholds before testing; report walk-forward sensitivity.
11. Baselines: random matched symbol/time, all +3..+10 events, RVOL-only, catalyst-only, acceleration-only, pre-breakout cohort. Metrics: precision@K, event hit rates with confidence intervals, median time-to-threshold, false positive rate, coverage, freshness rejection rate, and maximum adverse excursion.
12. Analyze winners AND failures by catalyst class, RVOL bands, float/market cap and market regime. Report calibration and confidence intervals, not merely winning examples.
13. Output separate historical_research/ and prospective_shadow/ ledgers. Every output includes provenance, dataset coverage, run version, missing-data counts and reproducibility metadata. Never copy historical events into the Oct-Nov 2026 experiment.

## Stage gates
A. Data feasibility: source and terms, 12+ months intraday history, delisted coverage, timestamp quality and cost documented.
B. Backtest: reproduce daily reference, first-seen and milestone calculations on hand-checked examples; pass no-lookahead tests.
C. Compare 3 families (momentum, catalysts, pre-breakout) against matched baselines on untouched test.
D. If robust, shadow-only independent forward test. No live orders.

## Current status
Research protocol created; data access, 12-month extraction, backtest and performance results **not yet validated**. No changes to existing SAG-30 experiment.
