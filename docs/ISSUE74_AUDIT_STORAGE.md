# Lossless storage and prospective audit — Issue 74

## What is retained

The current checkpoint transport retains every SQLite table/row and the immutable
first-WATCH/observation journals. SQLite backup includes committed WAL; restore
checks each part, compressed and raw hashes, quick_check and table counts before
replacement. Segmentation is transport, not a retention policy. No first_seen,
model rule, historical audit row, or original journal is rewritten by this PR.

`radar.checkpoint_audit` verifies the actual Git snapshot and journal inventory,
then compares its resolved commit with the remote radar-state ref. Its receipt
is separate from embedded health's PREPARED_NOT_CONFIRMED. Rewriting that embedded
health after pushing would create a different commit and is not proof of its own
publication. A later ref is reported as VERIFIED_HISTORICAL_SNAPSHOT, never as a
current receipt. A receipt is a point-in-time check, not indefinite durability.

```sh
git fetch --depth=1 origin radar-state
python -m radar.checkpoint_audit --ref FETCH_HEAD --out /tmp/publication-audit.json
python -m radar.checkpoint restore --ref FETCH_HEAD --out /tmp/radar-audit.sqlite3
git show FETCH_HEAD:shadow_first_watch.jsonl > /tmp/first-watch.jsonl
python -m radar.prospective_audit --db /tmp/radar-audit.sqlite3 \
  --session 2026-10-12 --watch-journal /tmp/first-watch.jsonl \
  --out /tmp/prospective-audit.json
```

Resolve FETCH_HEAD to a commit once for a multi-command audit; do not fetch again
between those commands. Keep large databases/reports outside the tracked tree.
These commands are read-only toward production; they require no market credentials.

## Quota and expiry risks remain unresolved

No indefinite, free, lossless storage solution is claimed. Current compressed
snapshot is approximately 96 MiB and growing. Per-part 64 MiB avoids the 95 MiB
blob rejection, but cumulative transfer, repository size, runner disk/time and
provider quotas remain finite. Full gzip changes repeatedly; splitting does not
make it efficient incremental storage. The orphan state branch has no reachable
Git ancestry retaining earlier snapshots; Git garbage collection may remove
unreachable objects. It is not an independent immutable archive.

Unpublished recovery/forensic artifacts have 90-day retention and are subject to
GitHub account storage quotas, deletion, upload failures and expiry. API outages
fail recovery closed. Recovery cannot restore rows from older failures that were
never persisted. Threshold alerts at 80/90 MiB remain active; increasing limits
or deleting rows is not the remedy.

Safe offload requires a separately provisioned durable object store with immutable
snapshot manifests, retained hashes/first_seen/journals, retention without automatic
expiry, protected deletion credentials, and independently tested restoration.
An archive must be durably acknowledged and restoration/replay verified before
any active partition is removed. No such external account or retention policy is
available here, so this PR **does not prune, partition or claim to solve unbounded
storage**. This is the issue's documented quota/expiry-risk alternative. Track
compressed bytes, upload durations, artifact quota and successful offsite restores
before choosing an archival implementation. An independent stale-alert service
also remains necessary when GitHub itself cannot run the radar.

## Audit interpretation

All observed scout symbols are denominators, including unselected symbols.
Earliest stored scout retrieval is discovery context, not an inferred signal.
Missing original price/source timestamps remain UNKNOWN. First deep observation
includes its original source timestamp, quality and reason. Stored global
first_seen/first_radar fields are exported separately and unchanged.

Only immutable journal WATCH records are used. WATCH availability is its actual
capture time, not an earlier price retrieval; a move preceding capture receives
no WATCH lead. Original FAST-PATH events remain SHADOW events, not BUY. No
historical WATCH, FLOW or precursor is reconstructed from later winners.

Later +15/+20/+30/+50 crossings use strictly subsequent same-session valid deep
snapshots, rejecting future or >900-second source trades even in old OK rows.
That 900-second diagnostic ceiling matches the existing collector default and
is not a new model gate. Already crossed targets at detection receive no lead.
All discovery/WATCH early_credit is zero: frozen EARLY-HOT evaluation is separate.
No follow-up and no observed crossing are censored; neither proves a false
positive. Sparse shortlist coverage cannot establish exact onset, market-wide
recall, a complete loser denominator, halt status, fill prices or tradability.
Session run universe/eligible/selected denominators are exported with coverage.

## Evidence and remaining acceptance checks

Snapshot 7b62251a7919c942e4d3151ee1279ab5d8f28b87 verified 47 tables and
1,263,039 rows; all declared journal hashes passed. Partial session cutoff
2026-10-12T17:44:58.749008Z: 1,574 observed discovery cohorts, 5,122 scout
samples, 229/229 valid deep samples, 122 logged first-WATCH records, 16 initial
late detections. 1,441 cohorts had no later valid deep sample; 133 had follow-up
without an observed later +30 crossing. This is coverage evidence, not efficacy.

Local full suite: 184 tests passed, including read-only database hash stability,
no backdated WATCH lead, late exclusion, invalid/future data, unselected discovery,
duplicate WATCH rejection and real Git manifest/journal/receipt validation.
Review both separate draft PRs before deployment. At least two post-review
production cycles remain unexecuted by design. Neither PR merges, places trades,
changes v0.3.3 FROZEN, touches SAG-Crypto or alters PR #71.
