# Data-source feasibility — 2026-10-26

## Candidates (research, not connected)
1. Alpaca Market Data: free/basic access to IEX real-time; documentation indicates historical SIP bars older than 15 minutes may be available on eligible accounts. IEX-only live observations are not market-wide. Authentication required; no API keys obtained or stored. Official references: https://docs.alpaca.markets/us/v1.1/docs/about-market-data-api ; https://alpaca.markets/learn/fetch-historical-data ; https://alpaca.markets/data
2. Databento US Equities: OHLCV-1m, timestamps, broad exchange datasets, historical pay-as-you-go. Quote cost before purchase; historical market coverage depends on selected dataset. No purchase or API keys obtained. Official references: https://www.databento.tech/catalog/us-equities ; https://databento.tech/docs/api-historical?lang=http

## Feasibility gates
- Check legal/licensing eligibility, API access, exchange scope and exact 12-month coverage.
- Confirm historical symbol mapping/delistings and adjustment policy, especially splits.
- Pull small representative sample including illiquid and delisted symbols, with known regular close and after-hours records.
- Measure bar completeness, timestamp semantics, timezone/DST and volume completeness.
- Request cost estimate for broad 12-month 1-minute OHLCV universe before expanding.
- Only then execute causal backtest. Until then: no performance statistics or claims.

## Research-only source ranking
Databento: preferred for rigorous broad-market history after coverage/cost check.
Alpaca: inexpensive prototype and independent spot checks; do not equate IEX-only data to consolidated market.
Both: historical replay strictly isolated from prospective ledger.

## Acceptance tests to implement
- no event whose source_timestamp > ingest time; no backdated first_seen
- no pre-first_seen high counted as subsequent threshold touch
- duplicate quote keys are idempotent
- stale quote excluded with reason
- prior close uses correct preceding regular trading day
- time-ordered walk-forward evaluation and embargo
- unavailable future observations are censored, not scored as failures or successes

Status: provider documentation researched; no API credentials, data download, backtest, or source integration executed.
