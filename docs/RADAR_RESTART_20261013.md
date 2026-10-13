# SAG-30 automatic restart investigation and proposed repair

## Observed before repair

The current main head was `892f8c64348fa6d5400c3bc22bbdf87dd6eaa558`.
The latest confirmed production collection workflow was
[run 38327971689](https://github.com/Ionut12345678/SAG-30/actions/runs/38327971689),
created at 2026-10-13 00:35:08 UTC and completed at 00:42:42 UTC
(03:42:42 Europe/Bucharest, 20:42:42 on October 12 in New York).
No newer radar run or in-progress run was returned at the investigation.

Its log proves:

```
00:35:24.916Z Outside configured U.S. observation window
00:42:39.939Z SAG30_CHECKPOINT_PUSH_PASS ... commit=f5965d40fd6677d8c3c1c9f29a5f64a93f739b7a
00:42:39.983Z Outside U.S. observation window; cadence chain stops.
00:42:40.000Z SAG30_CYCLE_PASS
```

This was a technical checkpoint publication, not a fresh market scan. Stored
health references collector run 530 from 2026-10-12 23:55:33 UTC, with 51
observations, zero valid observations, 51 source trades older than 900 seconds,
`MONITOR_DATA_GAP`, and `fast_path.status=NO_CURRENT_EVIDENCE` despite a
successful FAST-PATH step. FAST-SCOUT PASS does not validate deep market data.
The heartbeat generated at 00:42 UTC is not fresh evidence for the next day.

The durable checkpoint was independently verified by
[restore drill 38364865234](https://github.com/Ionut12345678/SAG-30/actions/runs/38364865234):
47 tables, 1,405,238 rows, database SHA-256
`2e619f427e720c9f703a36c80f8c938415c290586c94370bcad00c69112cc7ad`,
and SHA256_OK for all three WATCH journals. It is 113,417,276 compressed bytes
in two bounded parts. The storage-size warning is distinct from corruption.

## Supported causal conclusion and limit

The dispatch chain correctly terminated at the end of its 04:00–20:00 ET
weekday window. The next session had no self-starting chain: its sole starter
was the sparse `12,42 4-19` New York cron. No corresponding next-session
execution was delivered/visible. The separate free watchdog was diagnostic
only, ran on a fixed UTC window that misses early premarket/winter end, and
returned success even for WARN. Thus there was no independent restart or
failing alert to repair/flag an absent kickoff.

There is no evidence of an active lock, blocked job, failed push, or corrupt
checkpoint explaining this gap. `observe` was guarded only by main, so late
off-hours cron executions unnecessarily ran FAST-PATH/report/checkpoint work.
The `always() && persist success` dispatch condition protected persistence
but did not recheck the session after its cadence wait or exclude cancellation.

GitHub exposes no log for an event that never produced a run; the exact
internal scheduler reason cannot be established from this repository. Do not
claim timezone syntax is unsupported: GitHub now supports IANA schedule zones.
Its documentation also permits delayed/dropped scheduled events:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Proposed behavior after repair (not deployed)

- Independent UTC kickoffs at 08:00/09:00 cover both EDT/EST. Five-minute
  fallback wakeups cover the union of both UTC windows, including the next UTC
  day during EST. A shared ZoneInfo New York window admits only 04:00–20:00 ET
  weekdays, regardless of Romanian DST. The primary dispatch loop remains.
- Admission and collection share the existing workflow-level `sag30-state`
  concurrency group with cancellation disabled. Recently published cycles
  are skipped; another running radar blocks admission. Queued successors
  never bypass restore/recovery or overwrite a peer checkpoint.
- Read-only admission checks publication provenance, predecessor processing,
  and recovery artifact availability. Restore/recovery failure, missing
  recovery for an unpublished cycle, mismatched state identity, API failure,
  and ambiguous clocks block collection. A recoverable failed push enters the
  existing checksum/SQLite/audit-extension/journal recovery before scanning.
- The lease-protected state push and full audit history remain unchanged.
  No persisted locks, row pruning, first_seen edits or strategy changes.
- Dispatch excludes cancelled jobs and checks the window again after waiting.
- Source timestamp diagnostics include the latest quality-OK provider trade;
  source age is checked again at reporting time. Technical completion is
  explicitly separate from `DATA_GAP`/valid SHADOW observations.
- The read-only watchdog covers both DST windows, fails on active-session
  warnings, and uploads diagnostic evidence even on failure.

## Verification and remaining limits

`tests/test_restart.py` covers kickoff, resumption, due timing, session close,
weekends, U.S. DST, Romanian/U.S. DST mismatch, running/queued peers,
checkpoint/restore/recovery failure, missing metadata/API, valid-source versus
fresh-HTTP timestamps, and the actual dispatch shell crossing session close.
Existing checkpoint tests execute the actual publication shell against a bare
local remote, protect concurrent writers, and verify atomic recovery, rows,
first_seen and journals. Tests use synthetic clocks/data/APIs; no live dispatch.
Local tests and final PR CI results are recorded in the PR description.

The before/after comparison validates proposed controller behavior against
captured real metadata and synthetic failures. It does not prove a live
restart, future schedule delivery, or market-feed entitlement. Production
workflows were neither triggered nor stopped for this task. No merge means
main continues using the old mechanism until separately approved deployment.

GitHub cron is best-effort. Even redundant wakeups cannot guarantee a strict
300-second cadence when the scheduler drops all events, runners queue, or a
cycle exceeds 300 seconds. A separately hosted external observer is required
for an SLA/alert during a complete GitHub scheduling outage; none is installed
by this change. Real valid-source data must be rechecked after deployment;
deep preferred-feed entitlement remains false and this patch does not change it.

PR #89 is a separate draft for checkpoint capacity growth and remains untouched.
Its three files are not copied into this branch. PR #71, v0.3.3 FROZEN,
SAG-Crypto and BUY thresholds are unchanged. Everything remains SHADOW / NOT BUY.
