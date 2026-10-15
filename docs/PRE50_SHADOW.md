# PRE50 daily precursor — independent SHADOW pilot

**Source:** user-provided `PRE50_documentatie.pdf`, v0.1, dated 15 October 2026. This module is independent of the frozen SAG-30 rules and of the five-minute `shadow-lite.yml` scanner. No BUY/order/trading functionality.

## Original document's rules

Target: `High(t+1)/Close(t)-1 >= 50%`, not an achievable execution return. Eligibility: price $0.50–$30, average 5-day dollar volume >= $300k, at least 40 previous daily observations, exclude today's gain >=80%. Six weighted components: RVOL 25, 3-day acceleration 20, ATR5/ATR20 compression 15, close vs 20-day high 15, volume trend 15, close position within daily range 10. Thresholds WATCH 45, PRIORITY 65, ALERT 75.

**Explicit interpretation:** the PDF gives component maximum points but does **not** specify full continuous normalization curves. The piecewise linear/clamped mappings in `radar/pre50.py` are **our uncalibrated implementation hypotheses**, not claims that the source supplied these formulas. The source reports only synthetic test outcomes; no live predictive efficacy is established.

## Pilot operation

Workflow `.github/workflows/pre50-shadow.yml` schedules at **23:15 UTC on weekdays**, after the regular US close under both New York DST regimes, plus manual dispatch. GitHub cron is best effort. The pilot universe is the explicit **10-ticker** file `config/pre50_pilot_tickers.txt`, not the full SAG-30 universe. Daily OHLCV is downloaded via unofficial `yfinance` for 3 years, and any missing ticker aborts with DATA_GAP; the source can rate-limit, change or fail. Historical Yahoo daily prices may be adjusted for corporate actions and are not exchange-grade: review splits and ticker survivorship before treating any backtest as valid. Data source, coverage and exceptions are emitted as artifacts.

After fetching, `resolve` records actual next available trading-session **high** for previously recorded candidates, then `scan` scores the latest session and journals first_recorded_at. Journal is isolated in `pre50-shadow-state/pre50/journal.json`. The workflow persists it only on full success. Artifacts expire after 30 days. No claim of complete immutable audit until external evidence retention is added.

### CLI (requires existing real per-symbol CSV files)

```bash
python -m radar.pre50 backtest --data-dir pre50-out/bars --tickers config/pre50_pilot_tickers.txt --output pre50-backtest.json
python -m radar.pre50 scan --data-dir pre50-out/bars --tickers config/pre50_pilot_tickers.txt --journal pre50-journal.json
python -m radar.pre50 resolve --data-dir pre50-out/bars --tickers config/pre50_pilot_tickers.txt --journal pre50-journal.json
```

## Acceptance gates

1. CI unit tests pass on this PR.
2. Explicit authorized merge, then first real workflow run confirms actual coverage and journal persistence. A green unit test is not a live signal.
3. Forward-test at least 30 complete sessions and sufficient eligible +50% events; compare precision, lift and recall against eligible base rate, with all missed events counted.
4. Compare PRE50 T-1 selection against independent SAG-30 intraday SHADOW Lite in parallel. Do not combine or tune weights after observing test outcomes without a fresh holdout.
5. This is **SHADOW-only**; high(t+1) is not a tradable exit and no spread/halt/slippage is verified.

No Gate 0 legacy recovery, frozen v0.3.3, SAG-Crypto, PR #71 or live BUY behavior is modified.
