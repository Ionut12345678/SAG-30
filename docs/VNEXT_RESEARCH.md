# SAG-30 vNext — independent research prototype (SHADOW)

This branch starts a simpler radar research engine **without touching**
`radar.yml`, frozen v0.3.3, crypto, existing PRs, persisted checkpoints,
or signal bridge. It is not a production replacement.

## Why

- Discovery coverage was incomplete for many historical winners.
- Existing alert funnels did not establish a robust advantage over a
  simple +5..+10% baseline at similar alert volume.
- Market data and checkpoint persistence remain separate blockers.
- A credible new model requires a prospective, time-ordered, independently
  audited denominator, not survivor-only backtests.

## Prototype

`radar/vnext_research.py` reads **scout_history** in a copy of the existing
SQLite database. It records at most three new first-alerts per run per
strategy and never backdates first_signal_ts.

The vNext preselection requires:
- observed change from -2% to below +10%;
- positive acceleration, fresh turnover impulse, and turnover;
- one alert per symbol/session.

Baseline uses observed +5% to below +10%, highest first, with the **same
per-run slot cap**. The next 240 minutes of *recorded scout snapshots*
measure sampled relative return *after selection*, not daily gain since
prior close. Reports include +15, +20, +30, +50 and censorship.

Run on an independently restored **copy**:
```bash
python -m unittest tests.test_vnext_research
python -m radar.vnext_research --db /tmp/radar.sqlite3 --out /tmp/vnext_report.json --cap 3
```

## Required before any deployment

1. Fix checkpoint recovery and confirm at least two successful independent
   restores (including audit journals and integrity checks).
2. Verify source feed timestamps, quote ask/bid, halts and session boundaries.
   The current scout_history has no reliable executable ask or source
   timestamp for this report: **neither strategy is tradable**.
3. Run strictly prospective SHADOW for 10 complete market sessions with
   observation/failure denominators, fixed cap and no after-the-fact tuning.
4. Require a holdout comparison with matched source coverage and
   execution penalties before considering any operational change.
5. Separately evaluate misses from unobserved winners and false positives.
6. Do not deploy without fresh CI, reviewer approval, no active state writes,
   and explicit authorization. No changes to production workflow here.

## Data caveats

Censored/no forward samples are reported separately, never as losses. Measured
returns use sampled scout changes and can miss intracycle highs. Same-cycle
ranking may include feed-quality issues not represented in scout_history;
these are **not BUY signals**. Equal per-cycle capacity does not guarantee
equal realized counts. The prototype is a research baseline, not a claim
that vNext is better.

## Preregistered 10-session prospective acceptance protocol (2026-10-14)

**NOT STARTED / NOT LIVE.** This is a locked evaluation specification, not
evidence of ten completed sessions. Start counting only after an independently
verified production data collection cycle and a frozen evaluator commit.
Historical replay, backfilled rows, CI unit tests, and same-day partial sessions
do not count toward the ten sessions.

- Freeze the vNext and simple +5..+10 strategies, their three-per-cycle alert
  cap, eligible universe, clock rules, and evaluation horizon *before* session 1.
  Keep production SAG-30 and v0.3.3 FROZEN unchanged.
- Use identical observed scout cycles and timestamps for both strategies.
  Record feed identity, observation/source timestamps and age, skipped cycles,
  DATA_GAP, invalid records, and source-coverage denominators. No synthetic
  or retrospective `first_seen`; first alert must have a contemporaneously
  persisted, verifiable decision timestamp.
- Persist each session's candidate-level rows with strategy, ticker,
  first detection time, observed change and source, and WATCH/SHADOW status.
  Store later observed prices/changes and the first strictly post-alert
  sampled crossings of +15/+20/+30/+50, plus lead times. Distinguish
  **change from session reference** from **return since detection**.
- Record `UNKNOWN` execution unless contemporaneous bid, ask, spread, halt
  and quote freshness exist. No trading claims, no live BUY, no inferred fills.
- Keep outcomes `HIT`, `RESOLVED_NO_HIT`, `CENSORED`, and `NO_DATA`
  separate. Missing follow-up is not a losing trade. Publish false-alert
  counts only for fully resolved horizons.
- Report both absolute hits and hit rates with explicit denominators,
  source-coverage rates, time-to-first-alert, missed later winners,
  and alert-volume differences. Compare at equal per-cycle capacity and
  additionally at matched realized alert count; neither is a substitute
  for verified execution costs.
- Publish an immutable per-session report and a ten-session aggregate,
  with run URL, commit SHA, artifact checksum, session dates, and excluded
  sessions/reasons. Stop and mark `EVALUATION_BLOCKED` if checkpoint
  recovery or data provenance is not verifiable. Do not silently reset
  the start date or substitute backtests.

**Decision gate:** Ten complete, independently documented prospective
sessions with acceptable freshness and no critical data gaps are necessary
before even assessing superiority. Any production rollout requires separate
authorization, review, and demonstrated execution feasibility.
