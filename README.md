# SAG-30 FAST RADAR

Prospective cloud monitoring for **SAG-30 Early Radar v0.3.3 FROZEN SHADOW**. Discovery/routing only. **NOT BUY**.

## What is implemented

A Python 3.12 standard-library worker, GitHub Actions approximately five-minute scheduling, Alpaca snapshot collection, two-stage discovery/shortlist monitoring, SQLite audit storage, a durable state branch, conservative frozen-spec evaluation, Telegram delivery with a persistent retry outbox, and CSV/JSON audit exports. No pip dependencies or laptop are required after deployment.

The authoritative user-supplied specification is preserved verbatim in `rules/SAG-30-v0.3.3-FROZEN.txt`; its SHA-256 is enforced at startup. Never tune this version after winners/misses. A material change needs a new version and prospective validation start.

**Deployment and live-data validation have not been performed.** The default universe is intentionally empty and credentials are not included. This is monitoring infrastructure, not a validated autonomous signal classifier. The supplied frozen prose leaves semantic gates undefined numerically. The implementation cannot truthfully derive those gates from Alpaca snapshots alone: without sourced factual evidence it remains RADAR-LOW/WATCH/UNKNOWN, never manufactured HOT.

## Minimal cloud architecture

GitHub Actions timer → exchange-calendar/window check → broad snapshots every 15 minutes → top 30 by raw daily volume → shortlist snapshots on other approximately five-minute ticks → prospective database → frozen gates → Telegram outbox.

Raw daily volume ranking is an **operational discovery heuristic**, not RVOL, model confidence or a HOT gate. Universe membership is externally maintained U.S. small-cap coverage; no market-cap cutoff is invented by the model. Broad scanning is bounded by your universe, not the whole U.S. exchange. Keep it small enough for your provider limits. Newly emerging stocks outside that universe are discovery misses. Broad-discovery latency can be 15 minutes plus scheduling delay; shortlist latency is approximately five minutes plus scheduling/provider delay.

Actions schedules are best-effort, may queue or skip ticks, run on the default branch, and may be disabled after prolonged inactivity in public repositories. They are not a five-minute SLA. Actual times and gaps are recorded. A small paid always-on worker with the same SQLite on durable disk is the migration path if that SLA becomes necessary. Free Actions quotas depend on repository/account; consult current GitHub and Alpaca plans before enabling.

## Setup and deployment

1. Use a private GitHub repository if universe/audit data is sensitive. Push these files to the default branch. No deployment/push was done by the coding task.
2. Create an Alpaca paper account and enable market-data access. Add repository **Actions secrets** `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` using its paper credentials. The API calls use `paper-api.alpaca.markets` for the calendar and `data.alpaca.markets` for snapshots. The free `iex` feed is partial-exchange coverage, not consolidated U.S. volume; extended-hours or illiquid symbols may be stale/missing. Confirm current feed entitlements and limits. `sip` requires appropriate access; switching feeds is infrastructure configuration, not permission to change rules. Zero fresh data must not be presented as a successful market validation.
3. Populate `config/universe.csv` with `symbol,market_cap_usd,as_of` rows from a trustworthy U.S. small-cap universe source. Preserve the dated file in Git. This project does not download an undocumented/free screener or pretend market caps are available from snapshots.
4. Optional phone alerts: create a Telegram bot through BotFather, start a chat with it, obtain your chat ID securely, and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as Actions secrets. Missing notification secrets leave events queued. Every model alert carries the exact required NOT BUY label.
5. Enable Actions and allow workflows read/write contents permission. If branch protection disallows writes to `radar-state`, grant only the necessary exception. Leave main protected. Trigger `SAG-30 radar` manually and inspect logs plus the `radar-state` branch. Configure GitHub Actions failure notifications for scheduling/provider/persistence failures.
6. Confirm the calendar call, snapshots, quality records, actual cadence and state persistence across two runs before considering collection live. Verify a test Telegram message separately without manufacturing a market signal.

Each invocation makes one calendar request plus `ceil(symbol_count/100)` snapshot requests, with bounded HTTP 429/5xx retries, 30-second request timeouts and batch pacing. Keep discovery comfortably under the 10-minute job timeout and provider plan quota; long scans delay queued ticks. No API billing guarantees are made.

The window is 04:00–20:00 America/New_York, trading weekdays only, with holidays excluded using the provider calendar. DST follows the timezone database. Calendar-day filtering permits premarket and after-hours; early-close days still collect extended-hours snapshots until 20:00. An observation is never inferred from an open port, scheduled tick, cached result or missing response.

## Frozen evaluation and evidence

Architecture: DISCOVERY → CLASSIFY LANE → ACTIVITY CONFIRMED → PRICE CONVERSION → ACCEPTANCE/RECLAIM → EXPANSION PROOF → EARLY-HOT.

Numerical rules implemented: exact early bands (<5, 5–<10, 10–<15, 15–<20, ≥20), RVOL ≥3 with a verified baseline for confirmed activity, and subsequent observed new highs, ≥2 percentage-point reacceleration, or two positive intervals with rising observed highs. RVOL is one evidence family, never an independent HOT trigger; values above 10 receive no extra confidence. Catalyst is optional context. Decimal percentage computation protects exact +20% boundaries.

Semantic gates require contemporaneous, sourced evidence; the worker never invents a hold duration, retracement size, material giveback threshold, micro-consolidation algorithm, energy-memory extremeness or turnover baseline. A future trustworthy evidence adapter can provide `config/evidence.json` with the structure in `config/evidence.example.json`. A fact requires `value: true`, nonempty `provenance`, matching symbol and the exact observed SOURCE_TS. Static example facts default false. Do not set facts true just to obtain alerts. This is an integration contract, not automated validation of claims in the evidence source.

FRESH requires sourced lane classification, activity baseline, Price Conversion and Acceptance. SECOND_IMPULSE additionally requires `energy_memory`, `reset`, `rewake`, `no_absorption`; early credit also requires a sourced `rewake_pct` below +15%; these facts must respect the frozen previous-five-sessions/prior-winner context and early re-wake rules. OVERNIGHT additionally requires `preclose_ah_event`, `price_response`, `hold`, `premarket_continuation`. Those facts use the same value/provenance structure. Undefined Lane B/C semantics are WAIT unless evidenced, not numerical substitutes.

Acceptance is saved first. Only a **later observation and later SOURCE_TS** may prove expansion. Current trade prices prove new observed highs; accumulated daily highs are not used to backdate a signal. Expansion additionally requires sourced `acceptance_still_valid` and `no_absorption`. Two observations without a new high remain WAIT. Sourced `failed_acceptance` closes that episode and clears acceptance. A fresh session starts a new lane episode while global FIRST_SEEN/FIRST_RADAR_SEEN remain immutable. Unknown/conflicting observations cannot promote. Micro-consolidation breakout has no quantitative definition and is conservatively not automatically evaluated.

Early credit: <+5 EXCELLENT, +5–<10 IDEAL, +10–<15 EARLY VALID, +15–<20 SALVAGE; ≥+20 LATE-RADAR with zero early credit. Credit never implies buy eligibility. Separate report counters preserve salvage versus under-15 qualification. Replay must use a separate database; `replay=True` yields zero credit and no alert.

## Audit and timestamp semantics

RETRIEVAL_TS is stamped when the full response is received; SOURCE_TS is the latest-trade timestamp returned by Alpaca, never a substitute clock value. REQUEST_STARTED_TS records request initiation. All use timezone-aware timestamps. Payloads preserve daily/minute bar timestamps separately. Previous close is required, positive and dated before retrieval (maximum seven-day lookback); missing, future, stale, conflicting or invalid prices/timestamps are DATA_QUALITY with unknown percentage/band. Default 900-second source-age tolerance is a data-quality setting, not a model threshold; adjust to provider freshness requirements, not outcome optimization. Snapshot price and previous close are from the same provider/feed; independent-source conflict detection requires an additional adapter and is not claimed here.

Append-only-by-application observations include raw JSON and SHA-256, run IDs, quality reasons, source and retrieval times. Failed/closed runs are logged separately. FIRST_SEEN and FIRST_RADAR_SEEN have database update guards; signals point to the exact observed row and carry the spec checksum. SQLite is not cryptographically tamper-proof. Evidence JSON with its hash and evaluated reasons are retained with every observation; never retrospectively rewrite facts.

The separate `radar-state` branch persists the database even if the scan fails. A single workflow concurrency group serializes scans; do not run a second deployment against the same state. Scheduled jobs always restore that branch, with no force push; persistence errors fail the workflow. Telegram is at-least-once: a crash between delivery and acknowledgement can duplicate an alert. Event keys prevent duplicate event creation; failed deliveries remain queued. No model signals are sent if gates remain unresolved. Alerts are sent before the final state push: a push failure can also cause a repeated alert; inspect Actions failures.

Database growth is unbounded for audit integrity. Private repositories include source and market data; check your provider's redistribution/storage terms. Git history of binary databases grows quickly—this is suitable for a small initial shortlist. Archive securely and migrate to object storage/PostgreSQL before state approaches GitHub's file limits. Do not silently delete historical observations.

## Local checks and exports

```sh
python -m unittest discover -s tests -v
# Supply credentials as process variables; do not commit .env files.
python -m radar.runner
python -m radar.report
```

`RADAR_CONFIG` and `RADAR_DB` override paths. The runner does not load .env automatically. Tests use synthetic fixtures and mocked APIs, including a full collection/shortlist run, timestamp rejection, exact bands, activity-only blocking, chronological expansion, replay, late zero credit, immutable first-seen, alert success and alert failure retention.

Exported tables preserve the data needed to adjudicate TrueEarlyRadar10/EarlyRadar15, salvage, HOT→+30/+50, lane-specific outcomes, first-radar percentage and lead times. Report counters `hot_below_10`/`hot_below_15` are explicitly observed HOT-at-band counts, not claims that every stock was discovered. +30/+50 outcomes require an actual later recorded price relative to the previous-close baseline frozen at signal creation; unobserved intrainterval highs are not credited. False-HOT has no frozen failure horizon; SOURCE/DISCOVERY misses and MODEL misses require independent adjudication/coverage. They remain UNKNOWN rather than fabricated rates. Actual gaps are exported; overnight/day/session boundaries must be considered before counting cadence misses.

No live market-data, deployed schedule, cross-run GitHub persistence or real Telegram validation is claimed by local tests.
