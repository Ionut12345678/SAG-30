# SAG-30 SHADOW prospective validation protocol

Status: pre-registered research protocol, NOT validated BUY. Production v0.3.3 FROZEN is unchanged.

## Fixed candidate rules
- DISCOVERY: first contemporaneous observation with 0 <= change_pct < 10 and rank_change <= 100.
- PRIORITY: DISCOVERY AND rank_turnover <= 40.
- BASELINE: contemporaneous scout_history.selected.
- PRIORITY is a review queue, never a veto. DISCOVERY remains monitored.

## Unit, outcome and denominator
- Unit: one (session, symbol), using the FIRST eligible snapshot. Never retrospectively pick a better entry.
- Later observed +30/+50 means change relative to previous close at a STRICTLY later same-session timestamp; NOT tradable returns.
- Count every eligible followed candidate, including nonwinners. Report no-follow-up separately, never as a loss.
- Report exclusions, join coverage, timestamp freshness and sparse/absent observations.

## Locked future-session evaluation
- Collect at least 20 NEW market sessions after this protocol is published. Do not alter these thresholds during evaluation.
- Per session and overall: total eligible, later winners, true positives, false positives, recall, precision, alert load, and lead-time distribution.
- Include 95% Wilson intervals for binomial proportions. For paired differences, bootstrap by SESSION, not symbol, to preserve clustered market conditions.
- Publish day-by-day results including sessions with zero observed winners; do not cherry-pick.
- Any proposed threshold change starts a new version and a NEW prospective evaluation window.

## Execution reality
- Independently evaluate spread, liquidity, halts, quote freshness, slippage, fees, and realistic entry latency before discussing BUY.
- Avoid lookahead, survivorship bias, and comparisons across unequal follow-up windows.
- SHADOW results alone never authorize BUY.
