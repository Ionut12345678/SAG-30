# Radar Nou — independent infrastructure baseline

This is a NEW, offline-only, prospective SHADOW stock-radar prototype. The previous SAG-30 remains recoverable from Git history and prior branches; all legacy files and workflows are intentionally absent from the replacement tree.

### Scope and safeguards

- No broker API, no Alpaca, no BUY and no real transactions. Scheduled read-only website screening runs on GitHub Actions on weekdays, every 30 minutes in a best-effort window.
- UTC timestamps required, source freshness at most 120 seconds, first detection only between +5% and +10% vs previous regular close.
- Subsequent +15/+20/+30/+50 milestones and maximum observed gain are derived only from actual later observations (not historical day highs).
- NO DATA and absent follow-up are UNKNOWN, not false positives.
- Source coverage is unknown until an actual provider and comparable universe exist.
- Five complete real-market sessions validated: 0/5; profitability, recall and false-positive rate not established.
- GitHub Actions runs unit tests and public Nasdaq website screening. A successful workflow does NOT establish market freshness or executable entry prices.\n- Candidate first-seen and subsequent *reported* percentage moves are saved using Actions cache and uploaded as JSON artifacts. This is unverified website-snapshot history, not market-trade proof.\n- Cache persistence is best-effort, subject to retention and eviction; zero confirmed two-run recovery audits until validated.

### Run offline

Python 3.12:
```
python -m unittest discover -s tests -v
python radar.py --db radar.sqlite --feed sample_feed.json --output report.json
```

Sample JSON feed contract (sample is **synthetic**, not a live price):
```json
{"provider":"test-fixture","session":"2026-10-19","quotes":[{"symbol":"ABC","source_ts":"2026-10-19T14:30:00Z","price":10.6,"previous_close":10.0}]}
```

### Required before starting live operation

1. Connect a read-only independent data provider and validate symbol coverage and source latency.
2. Validate Actions cache restore/readback across at least two scheduled runs and identify gaps or evictions.
3. Use a scheduler with measurable actual execution cadence, not assumed perfect 5-minute GitHub cron.
4. Complete five genuinely observed sessions with market-wide denominators and post-detection follow-ups.

**Never create live signals from the sample feed.**

## Independent pulse fallback (hourly)

Because GitHub Actions `schedule` has not produced confirmed events in our Oct 19 audit, the read-only scanner also listens to versioned files added in `radar-pulses/` on the default branch. A separate scheduled ChatGPT task can write one unique, tiny file per hourly pulse (only during US trading-day monitoring hours). GitHub interprets this as a `push` event and triggers the scanning workflow, even when GitHub's own cron fails. This is a fallback and cannot guarantee a 5-minute or 30-minute frequency. Each pulse creates a trivial commit; no BUY or broker access. Monitor both the task result and GitHub run. The task depends on the GitHub app remaining connected and permissioned.

## Consistent screen snapshots

Candidate discovery and subsequent milestone tracking process one identical public Nasdaq response per scan. A quality artifact reports counts, follow-up coverage and data gaps. Source timestamps and market-wide coverage remain unverified; reported milestones are observational only. GitHub native cron and independent hourly pulse fallback are best-effort, not 5-minute guarantees.

## Prospective 5-minute cadence auditing

Each successful, nonempty public screen now records its actual UTC scan timestamp in recovered state. Later valid observations report the elapsed time since the previous successful collection, whether the measured gap met five minutes, and the number of five-minute intervals skipped. An unsuccessful feed does not count as a successful scan. This is measurement **only**: GitHub scheduled executions and the independent ChatGPT pulse do not become guaranteed 5-minute schedulers. The market data remain unverified website snapshots, never actionable BUY signals.
