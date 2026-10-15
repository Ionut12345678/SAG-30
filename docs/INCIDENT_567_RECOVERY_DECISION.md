# SAG-30 incident #567 — recovery decision record (2026-10-15)

**Status: UNRECOVERABLE FROM CONFIRMED GITHUB ACTIONS ARTIFACTS; GATE 0 BLOCKED.**

## Verifiable evidence

- GitHub Actions run [#38423433985](https://github.com/Ionut12345678/SAG-30/actions/runs/38423433985) (internal radar cycle #567) restored state and completed the prospective scan and checkpoint preparation. The checkpoint publication step failed; the recovery upload step was skipped after cancellation.
- GitHub Actions artifact listing for that run contains **only** `sag30-restart-diagnostic` (403 bytes); no `sag30-checkpoint-recovery` and no full SQLite checkpoint.
- `radar-state/health.json` generated 2026-10-13T15:35:03Z is stale. Its checkpoint says `PREPARED_NOT_CONFIRMED`, not a new successful publication.
- A passing unit test or a passing branch CI is **not** evidence of live recovery. No missing observations, first-seen timestamps or post-alert prices may be reconstructed from a market-day high.

## Safe disposition

1. Preserve the last verified published `radar-state` commit and audit journal; snapshot it independently, verify SQLite integrity and checksums. Do **not** alter or reset it.
2. Search any independently stored checkpoint or externally archived artifact for the **exact run #38423433985** with a verifiable manifest, parent commit, run identity and SHA-256. If found, use the existing `radar.recovery` verification path and audit-extension checks. **Only actual recovered evidence counts as recovery.**
3. If no such artifact exists, record the missing cycle as `UNKNOWN_NOT_RECOVERED` / `DATA_GAP` and preserve this record. **Do not** silently bypass `UNPUBLISHED_CYCLE_WITHOUT_RECOVERY` or claim Gate 0 PASS. A separate, explicit operator-approved decision and separately reviewed safe-resume design would be required to start a *new* prospective series from the last verified checkpoint, and that does not recover the missing cycle or satisfy the preregistered Gate 0 retroactively.
4. After genuine recovery, require current-head CI PASS, isolated failure-injection exercise, two consecutive real successful published checkpoints and measured start-to-start cadence, source freshness and DATA_GAP before opening Gate 1. Keep PR #92 and PR #93 unmerged until explicit authorization.
5. At 2026-10-16 16:00 Europe/Bucharest, if Gate 0 is not proved, issue **INFRA_STOP** without deadline extension.

## Preventive patch

PR #92 now uploads `sag30-checkpoint-recovery` **before** the remote push, refuses publication if the backup upload fails, retains the backup on failure/cancellation, and deletes it only after successful publication. Restart diagnostics explicitly identify the blocked run and evidence status. Synthetic tests verify the guards. The extra artifact upload can increase cycle duration and must be measured; it does not resurrect run #567.

**No live BUY, no trades, no frozen v0.3.3 changes, no audit rewriting.**
