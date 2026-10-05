# Production universe snapshot — 2026-10-05

`universe.csv` is the exact, sorted radar input: **3,185 unique U.S.-listed symbols** with reported company market capitalization **greater than $0 and strictly below $2 billion**. This intentionally includes micro- and nano-caps, not just the conventional $300m–$2b small-cap band. Market-cap boundaries select discovery coverage only; no frozen SAG-30 v0.3.3 detection rules or thresholds were changed.

| Listing exchange | Symbols |
|---|---:|
| Nasdaq | 2,350 |
| NYSE | 615 |
| NYSE American | 220 |
| Total | 3,185 |

| Reported market cap | Symbols |
|---|---:|
| >$0–<$50m | 925 |
| $50m–<$300m | 922 |
| $300m–<$2b | 1,338 |

Scope is **U.S. exchange listings, not U.S.-domiciled issuers**. Common equities, ordinary shares, positively identified ADRs/ADSs, REIT/BDC equity and identified common partnership units are eligible. Foreign issuers and SPAC common shares are not automatically excluded. Multiple eligible share classes remain distinct symbols. There is no price, volume, catalyst or performance filter.

## Sources and provenance

- [Nasdaq stock screener](https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25000&download=true): 7,001 records; reported market caps, names, country and industry.
- [Nasdaq Trader nasdaqlisted.txt](https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt): 5,636 listing records, security names, ETF/test/NextShares flags. Includes Nasdaq's market tiers.
- [Nasdaq Trader otherlisted.txt](https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt): 7,653 records; only exchange code N (NYSE) and A (NYSE American) accepted. NYSE Arca and other exchanges are excluded.

Sources were retrieved on **2026-10-05 at approximately 20:05:28 UTC**. The symbol-directory creation marker is `1005202615:41`; its raw representation is retained without inventing a timezone. The screener's `asOf` is null: its valuation SOURCE_TS is **UNKNOWN**. CSV `as_of=2026-10-05` means **UTC retrieval date**, not a claimed quote/valuation source timestamp. HTTP Date is transport metadata, not market SOURCE_TS.

`universe_metadata.json` preserves individual request/retrieval timestamps, nullable source timestamps, raw creation markers, URLs, hashes, selection policy and counts. `universe_sources/*.gz` contain the exact source responses, enabling offline reproducibility. `universe_details.csv` joins symbols to exchange/security name/country/financial-status metadata; `universe_exclusions.csv` records every excluded screener record and its first applicable reason.

## Coverage limitations

- Current directory inclusion verifies listing, **not** a live trading status, absence of halts, broker eligibility, Alpaca `tradable=true`, shortability or IEX coverage. Alpaca secrets were unavailable; no authenticated per-symbol assets/snapshot checks were performed. Suspended or inaccessible symbols must remain missing/DATA_QUALITY in collection, not fabricated observations. Nasdaq deficiency/bankruptcy financial-status flags are retained for audit, not treated as proof of delisting.
- 387 screener records have missing/invalid market cap and were excluded; 2,988 are outside the positive <$2b boundary (including zero/nonpositive caps). No valuations were guessed.
- 299 derivative/non-common records, 96 named funds/income trusts, 18 ambiguous/pooled beneficial-interest records, and 28 unclassified security descriptions were excluded. Type classification is deliberately conservative and based on source names/industry; it is not a complete security-master taxonomy. Some genuine common stocks with incomplete descriptions are excluded, and name-based fund detection is not guaranteed exhaustive. See the exact exclusion CSV before interpreting misses.
- ETFs, NextShares, test issues, warrants, rights, preferred shares and debt are excluded. OTC and non-target exchanges are outside scope. A symbol must match the collector's supported letters/numbers with optional dot/hyphen class suffix.
- Market caps are vendor-reported, potentially delayed, and are not recomputed or verified across vendors. Changes, IPOs, delistings and newly reported caps after retrieval are absent until refresh. This is a **dated static snapshot**, not an automatically maintained market-wide universe.
- The existing free `iex` feed covers one venue, not consolidated U.S. trading. Listing coverage does not guarantee fresh prices/volume on that feed, especially during extended hours.

## Refresh and validation

```sh
# Reproduce the committed snapshot without network access:
python scripts/build_universe.py
# Fetch new public snapshots (requires api.nasdaq.com and www.nasdaqtrader.com):
python scripts/build_universe.py --refresh
python -m unittest discover -s tests -v
```

Review changes, source timestamps, inclusion/exclusion counts and anomalies before committing a refreshed universe. Do not tune the selection based on individual winners/misses or alter the frozen model. Refresh is not scheduled automatically by this change.

3,185 symbols require **32 snapshot batches** (100 symbols each) per 15-minute discovery sweep; monitoring remains the existing maximum 30-symbol shortlist at approximately five-minute ticks. Including the calendar call, a discovery tick needs 33 provider requests before retries. Provider quotas and GitHub scheduling/scan duration still need live verification. No market-data validation, deployed workflow success or alerts are claimed by the universe tests.
