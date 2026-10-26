# Radar v2 research implementation status

PR-only, no production modification, no broker orders.

## What exists
- `causal_engine.py`: prospective prototype (in-memory, no persistence).
- `offline_evaluator.py`: deterministic offline replay sorted by ingestion timestamp.
- `test_causal_engine.py`, `test_offline_evaluator.py`: 18 synthetic regression tests.
- `.github/workflows/radar-v2-research-tests.yml`: read-only pull-request unit-test job.
- `PROTOCOL.md`, `DATA_SOURCES.md`: causal study and data feasibility gates.

Run from repository root:
```bash
python -m unittest discover -s research/radar_v2 -p 'test_*.py' -v
```

## Blocking gaps — do not claim a profitable radar
1. No verified 12-month intraday US universe with corporate actions and delistings; provider credentials/coverage/licensing and pricing not confirmed.
2. No point-in-time previous regular-session close validation across splits, holidays, DST.
3. No persistent production-quality immutable quote/event store, restart recovery, multi-day sessions or premarket classification.
4. No causal news/catalyst ingestion, RVOL/float features, matched controls or walk-forward backtest.
5. No untouched holdout performance results; no demonstrated predictive advantage.
6. No live scan connected to this branch. Existing Oct-Nov 2026 prospective study remains unchanged.
7. Tests are synthetic; GitHub CI run status must be checked separately. Workflow file is not proof of a successful run.

## Release gates
- Verify CI on PR and address failures.
- Obtain legal timestamped historical data; validate completeness and costs.
- Implement corporate action/session-aware reference closes, event-level persistence and audit.
- Run leak-free chronological train/validation/test with negative controls and report confidence intervals.
- Only then consider separate prospective SHADOW evaluation. Real trading remains disabled.
