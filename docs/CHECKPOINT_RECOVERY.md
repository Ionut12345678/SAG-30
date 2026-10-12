# Radar checkpoint repair and recovery

Infrastructure only: v0.3.3 FROZEN, scout selection, FAST-PATH rules, all SHADOW/PAPER gates, SAG-Crypto and PR #71 are unchanged. No trade/order API is introduced. This change is reviewed in a separate PR; it does not deploy itself.

## Diagnosis and evidence

The workflow compressed the entire SQLite file and refused publication at **95 MiB**, after collection, FAST-PATH, reports and heartbeat generation. It then self-dispatched even when publication failed, repeatedly restoring an older database. `health.json` could therefore be generated locally but never reach `radar-state`.

The last readable state ref examined was `604c23b66d6688a37fed50933cb7bb06435cec6a`: 99,014,002 compressed bytes, 470,642,688 SQLite bytes. SQLite quick_check passed. Only 904 of 114,903 pages were free (3,702,784 bytes); evidence, observations and semantic/scout history accounted for most space. Removing free pages would buy little time, and deleting old history would invalidate prospective audits.

[Run 38272567681](https://github.com/Ionut12345678/SAG-30/actions/runs/38272567681) had successful observation, FAST-PATH and heartbeat steps, a failed persistence step, and a successful dispatch step after that failure. These are job-step conclusions, not proof of fresh market data. Its artifact listing was empty. Raw log downloads were blocked at GitHub's redirected log host; the exact failed-run compressed byte count was not observed. No unavailable failed-run observations are reconstructed or backdated.

See `reports/checkpoint_repair_validation_20261012.json` for the read-only real-snapshot row counts/hashes, source ref, round-trip timings and health diagnostics.

## Lossless format

`radar.checkpoint prepare` uses SQLite's backup API to capture all committed pages, including WAL transactions, without modifying the source. It runs quick_check and records every table's row count. No rows, timestamps, first_seen values, payloads, indexes or model state are pruned; no schema is migrated. Compression remains gzip level 6.

The compressed byte stream is split into parts of **at most 64 MiB**, each strictly below the old 95 MiB per-file cap. `checkpoint.json` records format, ordered names, part sizes/SHA-256, whole compressed/uncompressed SHA-256, table counts, restored parent commit and workflow run identity. The manifest is written last. The state ref is a complete one-commit snapshot, as before; the audit history remains inside SQLite.

The 80/90 MiB alerts measure **total compressed SQLite**, not each part: WARNING at >=80 MiB, CRITICAL at >=90 MiB. They emit GitHub warning annotations, a step summary and heartbeat fields. They do not imply trading signals or send model alerts. Crossing 95 MiB no longer discards the database; its parts still obey the per-file safety limit. The implementation does not pretend sharding reduces total storage growth.

`health.json.checkpoint.publication=PREPARED_NOT_CONFIRMED` is deliberate: embedding the yet-to-be-pushed commit's hash in itself is circular. A prepared file alone is not durability proof. Publication is confirmed by a successful lease-protected ref update, a matching subsequent `ls-remote`, and `SAG30_CHECKPOINT_PUSH_PASS ... commit=...` plus the GitHub step-summary receipt. Fetch the exact receipt ref and verify its manifest before calling it durable. The final workflow verdict cannot print CYCLE_PASS after publication/FAST-PATH failure.

## Restore and failure recovery

All in-repository state consumers now use the same verified restore module. It supports legacy uncompressed SQLite, legacy single gzip, and the new multipart manifest. Multipart restore verifies each part, whole gzip, expanded SQLite hash/length, SQLite quick_check and every table's row count, then atomically replaces the destination. Any failure leaves the prior destination intact. No fallback to an older format is allowed when a manifest exists but is damaged. Restoring over WAL/SHM sidecars is refused.

Publication uses a force-with-lease tied to the exact restored `radar-state` ref, never unconditional force. A concurrent writer cannot be silently overwritten. A lost push acknowledgement is recognized by checking whether the remote already holds the identical outgoing commit before retrying. Failed publication uploads `sag30-checkpoint-recovery` with the complete prepared database and first-WATCH journals; self-dispatch stops. The watchdog can restart later.

Before the next scan, `radar.recovery` looks for a nonexpired artifact from `radar.yml` on main whose manifest parent exactly equals the restored state ref and whose recorded run matches the artifact's run. It verifies/restores the full snapshot and journals before collecting new observations. It additionally rejects removal/modification of published append-only evidence and changes to existing global first_seen/first_radar values. First-WATCH journals must extend the published byte prefix; new manifests inventory their sizes/hashes. Legacy v1 manifests without journal inventories remain readable, with prefix protection. Artifacts from unrelated parents/branches are not silently merged. API failures, recent expired artifacts, corrupt artifacts, or unresolved recent forensic snapshots fail closed. The workflow requires `actions: read`, uses its existing GITHUB_TOKEN, and needs no new secret.

Preparation failures upload `sag30-checkpoint-forensic` (raw database/WAL plus available first-WATCH journals/health) for operator adjudication. Automated recovery intentionally cannot declare a corrupt raw database trustworthy. Retention is requested for **90 days**, subject to repository policy and artifact quotas. Export recovery artifacts to durable external storage before expiration. If both publication and artifact upload fail, remote preservation is unconfirmed; alerting/Actions failure notifications must be monitored. Runner cancellation before upload can also leave a gap. This PR cannot restore observations from old failed runners that never saved an artifact.

## Manual investigation/recovery commands

Run in the source checkout with Python 3.12. Use an isolated destination; never decompress directly over a live database. Do not create additional worktrees just for this procedure.

```sh
git fetch --depth=1 origin radar-state
python -m radar.checkpoint restore --ref FETCH_HEAD --out /tmp/sag30-verified.sqlite3
# Download a known failed-publication artifact (needs repository Actions read access):
gh run download RUN_ID --repo Ionut12345678/SAG-30 --name sag30-checkpoint-recovery --dir /tmp/sag30-recovery
python -m radar.checkpoint restore --directory /tmp/sag30-recovery --out /tmp/sag30-recovered.sqlite3
python -m radar.health --db /tmp/sag30-recovered.sqlite3 --out /tmp/sag30-recovered-health.json
```

Compare the artifact's parent commit/run identity with the restored live ref before adopting it. First verify audit rows, source/retrieval timestamps and first_seen fields. Do not replace a newer live checkpoint with an unrelated artifact or reset first_seen to repair a gap. For concurrent-writer conflicts or forensic WAL snapshots, preserve both inputs and require an explicit reconciliation rather than silently discarding either history. Do not enable another writer or manufacture replacement signals.

## Rollout and remaining limitations

Before the first multipart publication, pause new radar scheduling/dispatch and drain legacy runs so an old unconditional-force writer cannot overwrite the new format. Preserve the current ref externally. Review/merge the repair manually, then resume and verify two actual cycles. No production state ref or workflow was changed during local validation.

Check the confirmed publication receipt, fetch/restore that exact ref, inspect health.json generated time versus latest_run/source times, inspect DATA_GAP separately from persistence, verify FAST-SCOUT eligible counts and FAST-PATH current evidence, and measure actual run/observation gaps. The watchdog and 300-second target remain unchanged; `MISSED_TARGET` compares stored same-session run starts against the configured target, with session boundaries separated. Passing clock arithmetic is not a live five-minute SLA. Premarket routing-only FAST-PATH mode is explicit and is not credited as live minute-loop evidence. An old run can never be presented as current evidence just because checkpoint preparation ran today.

The last saved snapshot still has DATA_GAP/stale quotes and a 492.122-second stored cadence gap. Local restoration is not a fix for provider entitlement/quote freshness or scheduler latency. No Alpaca secrets were available for live validation, and GitHub-hosted artifact upload/recovery and post-merge cadence have not run this new implementation. Old unrecoverable gaps remain gaps.

Sharding removes the immediate single-blob ceiling, but total database/network cost still grows. GitHub pack/repository limits, auxiliary journals, artifact storage costs/retention and the 12-minute job budget remain operational constraints. Plan a separately reviewed durable audit archive/hot-state migration before total checkpoints become large; do not solve that by dropping audit rows. Generic auxiliary file-size limits are not changed by the SQLite format.


## Pre-deployment review of PR #73

Reviewed original head `8117a3991af6d5f226c4e098424dffcd92846147` against main `d4d33f23a65839933235700a46d879ec377bb7b5`: all 30 changed files were inspected. All 20 auxiliary workflows require multipart compatibility. Comparing parsed YAML and normalized restore blocks found no unrelated research commands, report destinations, triggers, job settings or permission changes in those original auxiliary diffs. Nothing unrelated needed removal; reverting those restore changes would break the readers when multipart state is published.

Review fixes: a skipped recovery after a failed journal step can no longer authorize scanning or checkpoint preparation; success is required for existing state, with a separate fresh-initialization case. Journals now join the hashed checkpoint inventory, and recovery checks published audit/first_seen invariants before replacement. Copy failures leave the database intact and clean up staging files. Nonpositive cadence gaps are INVALID_SEQUENCE, and missing FAST-PATH evidence/failure is reported separately from a successful FAST-SCOUT or a storage-size warning.

The existing rank-ledger test workflow also gains an isolated synthetic artifact contract job. It uploads a tiny checkpoint and downloads it through the exact GitHub artifact ZIP API route to verify layout, SQLite restoration and journal hashes without market secrets, production writes or model signals. Its actions:read permission is job-local. This is additional checkpoint validation, not a production deployment or a research-rule change.

Per-file review inventory:

| File | Review result |
|---|---|
| `.github/workflows/benchmark-probe.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/broad-scout-precursor-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/compression-probe.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/dq-diagnostic.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/precursor-case-probe.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/precursor-winner-gate-audit-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/radar.yml` | Persistence/recovery wiring, readiness gates, bounded state, alerts and publication receipts; rollout main-only |
| `.github/workflows/rank-ledger-tests.yml` | Required restore compatibility; additional isolated real-artifact contract CI |
| `.github/workflows/scout-fastpath-handoff-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/shadow-prospective-ledger.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/topp-cross-session-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/topp-reconstruction-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/topp-reconstruction-v2-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/v0410-routing-rescue-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/v0411-clean-acceleration-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/v0411-coherent-window-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/v048-compare.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/v048-replay-benchmark.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/v049-precursor-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/v049-sbfm-dki-reconstruction.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `.github/workflows/winner-audit-dev.yml` | Required checkpoint transport only; original research/report/trigger/permissions unchanged |
| `docs/CHECKPOINT_RECOVERY.md` | Diagnosis, provenance, recovery/rollout instructions and remaining limitations |
| `radar/checkpoint.py` | Full WAL-aware backup, bounded parts, hashes, journal inventory, atomic restore and legacy compatibility |
| `radar/health.py` | Operational diagnostics only; DATA_GAP/storage/cadence/FAST-PATH remain distinct |
| `radar/recovery.py` | Parent/run provenance, published audit and first_seen protection, journal-prefix checks, fail-closed recovery |
| `reports/checkpoint_repair_validation_20261012.json` | Read-only checkpoint row counts, logical hashes and explicitly scoped validation evidence |
| `tests/test_checkpoint.py` | Regression/integration fixtures; no production writes or market requests |
| `tests/test_checkpoint_health.py` | Regression/integration fixtures; no production writes or market requests |
| `tests/test_checkpoint_publication.py` | Regression/integration fixtures; no production writes or market requests |
| `tests/test_checkpoint_recovery.py` | Regression/integration fixtures; no production writes or market requests |
