# SAG-30 — audit winner-first, 12 Oct 2026 (SHADOW)

**Source:** `radar-state/winner_recall_report.json`, read at time of report construction. This report is descriptive, NOT a model validation or BUY approval. Source audit has `authoritative:false` and only covers prospectively recorded sessions after full-universe scout_history deployment.

## Winner-first: why the model misses them

Cohort: **100** symbol-sessions with a subsequent observed +30% or more. **60** reached +50%. The classification is for whether there was evidence and a model stage below +10% *before the first observed +30%*.

| Failure stage | Count | Fraction of winner cohort |
|---|---:|---:|
| SCOUT_MISS | 60 | 60.00% |
| SHORTLIST_MISS | 14 | 14.00% |
| DEEP_TIMING_MISS | 11 | 11.00% |
| BASELINE_MISS | 8 | 8.00% |
| MODEL_MISS | 6 | 6.00% |
| EARLY_HOT_SUCCESS | 1 | 1.00% |

- Under-10 scout coverage: **40%**. Thus **60 / 100** winners lack an eligible pre-+10 scout observation. This might reflect first discovery already over +10, provider/data coverage, or sampling cadence; it is **not proven** to be a ranking or model defect without coverage diagnostics.
- Base shortlist recall under +10: **19%**. Any shortlist recall: **26%**. HOT recall under +10: **1%**.
- **Do not compare these winner-conditioned recall metrics with unconditional model precision as if the denominators matched.**

## Candidate-first: how many selected candidates become observed winners

Prospective `early_shortlist_outcomes` reports **2229 finalized selected symbol-sessions**, plus **235 pending**. Among finalized entries: **23** later crossed observed +30% (1.03%) and **12** later crossed observed +50% (0.54%). These are observation-based cohort outcomes, not tradable profits.

## Frozen prospective 12 Oct first-WATCH sanity check

The live first-WATCH JSONL review, at ~18:47 UTC, contained 199 watches; 165 were first detected between -10% and +10%; of those, 160 had later observations and **zero** later +30/+50 observations in the snapshot. Other watches that crossed thresholds were first registered above +10. These snapshots are *not* the same dataset as the multi-session winner recall above and were still open; do not pool denominators.

## Falsifiable next experiment (do not tune on the holdout)

1. **Coverage audit first.** For each of 100 winners, reconstruct first available retrieval time, price delta at that time, provider source timestamp/age, missing bars and earliest observed sub-10 reading. Assign explicit outcome: already-over-10-on-first-observation, data_gap, pre-10-available-but-scouter-missed, or ambiguous. Never pretend unobserved earlier readings existed.
2. **Baselines on identical universe/time/data:** (A) first genuine observable +5% crossing with minimum consecutive observations and turnover/volume; (B) first eligible +5-to-10% snapshot; (C) current frozen scout + shortlist + HOT. Record alert budget per day and time-to-+30/+50, not just recall.
3. **Lock thresholds on past development sessions only**, then evaluate on later untouched sessions, including ALL alerted nonwinners. Report recall, precision, false positives/day, candidate age/source coverage, hypothetical entry spread/slippage, net-of-cost feasibility, and bootstrap intervals. Report unobservable observations separately.
4. **Decision:** promote challenger only if out-of-sample improvement over simple baseline is material at a comparable alert budget and executable data quality. If no improvement, retire/replace the selection logic without changing v0.3.3 FROZEN.

## Guardrails

No buys, no backfill of earlier detection, no automatic merge of model rules, no audit deletion, no retrospective selection using the target label. The observed +30/+50 change is relative to session reference, not post-entry percentage return.
