# Live restart validation and early-dispatch regression

Production validation was authorized after PR #90 was merged as
`707b07dfffd47757c73227f31d04438d4c90a69a`. All collection remains SHADOW.

## Observed evidence

| Run | Trigger | Result |
| --- | --- | --- |
| [557](https://github.com/Ionut12345678/SAG-30/actions/runs/38412753926) | Manual, 14:22:15 UTC | Restored 47 tables / 1,405,238 rows; 47/48 valid observations; published checkpoint; dispatched 558 |
| [558](https://github.com/Ionut12345678/SAG-30/actions/runs/38413565970) | Automatic repository_dispatch, 14:27:50 UTC | Restored 47 tables / 1,420,636 rows; 54/55 valid observations; published checkpoint; dispatched 559 |
| [559](https://github.com/Ionut12345678/SAG-30/actions/runs/38414288631) | Automatic repository_dispatch, 14:32:50 UTC | Admission SUCCESS but observe SKIPPED: NOT_DUE at 272.928601 seconds |

557 published state commit `5ee9ee6932ef94d2d5b32245047c020cbeeb13a4`
at 14:26:24 UTC, 113,811,395 compressed bytes. 558 published
`2fca988f4f7f76f5cb1d7a56e0b80bb232fd2aa8` at 14:31:56 UTC,
114,217,849 compressed bytes. Both final logs report
`VALID_OBSERVATIONS_SHADOW_ONLY` and `SAG30_CYCLE_TECHNICAL_PASS`.
558's latest valid provider timestamp was 14:28:37.359579 UTC;
FAST-PATH had current evidence through 14:31:24.733414 UTC.

## Defect found by validation

The existing dispatch controller compensated 37.915661 seconds of observed
startup latency. The new admission gate requires 300 seconds since the prior
scan and skipped the compensated successor when it arrived early. A skipped
observe job cannot dispatch another successor. This interaction interrupted
the chain despite two successful live cycles. SUCCESS alone is insufficient.

## Proposed follow-up

For repository_dispatch only, a NOT_DUE admission waits the remaining seconds
under the existing concurrency lock, then rereads remote state and rechecks all
admission conditions. The wait is bounded to 61 seconds (the controller's
60-second compensation plus rounding), within the existing five-minute timeout.
Unexpected longer waits or a still-NOT_DUE second decision fail explicitly.
Scheduled/manual duplicate wakeups retain their existing skip behavior.
No workflow, checkpoint, strategy, provider entitlement or BUY threshold changes.

Four regression tests cover the exact observed early arrival, checkpoint/peer/
session changes during the wait, bounded waiting, and no wait for due/blocked
cycles. The local full suite passed 254 tests. CI is recorded in the follow-up PR.
This follow-up is not deployed merely by creating its draft PR.

## Remaining limits

Automatic repository dispatch is observed; independent cron kickoff and future
DST transitions are not yet proven live. The checkpoint size warning remains
above 90 MiB; all audit rows are retained. The observed scan gap was 337.916
seconds versus the 300-second target. No strict scheduler latency SLA is claimed.
The semantic model remains blocked where frozen evidence is undefined; valid
market observations do not imply a BUY. PR #89 remains a separate draft.
