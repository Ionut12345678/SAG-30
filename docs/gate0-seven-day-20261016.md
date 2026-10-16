# SAG-30 — seven-day evidence gate (SHADOW ONLY)

Window: 16–23 October 2026 UTC. Existing FROZEN model is unchanged.
No live trading or BUY. No filter tuning during the evaluation.

## Decision rules

1. At least 95% of **eligible US market-session 5-minute scan slots** must have a traceable run; count missing slots, do not count successful CI as market scans.
2. Every FIRST_WATCH needs measured T+1, T+2 and T+5 **trading-session** highs and coverage flags; missing observations are DATA_GAP, never 0% returns.
3. Compare signals to a predeclared matched control set of nonselected stocks, matched by market cap, liquidity, baseline return and observation time. Do not claim an edge before this control is available.
4. Separately record price freshness, spread, halts and possible execution slippage; observed highs are not executable returns.

Gate is HOLD until all criteria have data and pass. At the end of seven days, report PASS/HOLD/STOP; stop further model development if evidence is insufficient. T+5 outcomes for alerts near the end of the window require additional trading sessions before final verdict.

## Implementation status

`radar/gate0_seven_day.py` creates a fail-closed audit summary from saved state, read-only recovery outcomes and workflow-run metadata. This is a **baseline evidence evaluator**, not yet an automated end-to-end 7-day collector. Cadence slot denominator, matched control and T+1/T+2/T+5 historical backfill are intentionally NOT_MEASURED until implemented and validated. Do not interpret these placeholders as successful validation.

Recommended prerequisites for operational deployment: PR #103 freshness gate, PR #99 completed-session guard, PR #108 schedule watchdog and PR #107 tests. Each remains subject to separate review and merge authorization.
