# Issue 74 operational diagnosis and review plan

Evidence inspected 2026-10-12 UTC, read-only, before these changes:

* Run 38285295043: scan 17:36:22–17:36:28; FAST-PATH through
  17:39:14; checkpoint prepare 17:39:22–17:39:34; publication finished
  17:39:43; dispatch finished 17:41:22. Every listed step succeeded.
* Following published run 464: start 17:41:36.293533 UTC, cadence
  313.731 seconds; 3,185 universe, 1,258 eligible, 66/66 valid deep observations,
  315 current SHADOW FAST-PATH events. No DATA_GAP.
* Published checkpoint 100,934,195 compressed bytes, two parts, largest
  67,108,864 bytes. CRITICAL_90_MIB and MISSED_TARGET independently explain
  DEGRADED. Model BLOCKED_SEMANTIC_EVIDENCE is separate from infrastructure.
  This does not establish early-detection efficacy or tradability.

## Changes

Health emits explicit reason_codes, including independent storage warnings,
without manufacturing a market DATA_GAP. Quote age, bid/ask validity and spread
are diagnostics: neither a fresh quote nor a SHADOW route proves executable
liquidity, a fill, an entitled consolidated feed, or absence of a halt.
Existing trade quality gates and frozen evaluator are untouched.

Dispatch previously waited until 300 seconds after scan start, then incurred
runner/restore startup. Bounded feedback (0–60 seconds) compensates observed
same-session overhead using the preceding published health offset. It reduces
the offset when observations arrive early; overnight/outage/inverted gaps reset
it. It never alters timestamps, increases provider concurrency, dispatches before
successful publication, or removes the sag30-state single-writer guard.
Actions queue time is variable; approximately five minutes is a target, not an
SLA. The New York weekday 04:00–20:00 watchdog remains every 30 minutes;
GitHub schedule delays can exceed that. An independent external monitor is
still required for reliable wall-clock stale alerts when Actions itself stops.

## Review and rollout (not executed by this PR)

Review the draft and pause/drain older writers before any authorized rollout.
After review and deployment, record at least two consecutive production cycles:
start/start gap; scan/FAST-PATH durations; publish receipt; compressed size;
health reasons; universe/eligible/deep valid denominators; trade and quote ages;
provider errors and UNKNOWN halt/execution fields. Compare with evidence above.
Unit tests and PR CI do not replace those production observations. No deployment,
orders, automatic merge, or live credential validation is performed here.
