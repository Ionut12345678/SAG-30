"""Classify PRE50 observation completeness from workflow outcomes."""


def classify(coverage, outcomes, scan=None):
    requested = coverage.get("requested")
    fetched = coverage.get("fetched")
    complete = (
        isinstance(requested, int) and requested > 0
        and isinstance(fetched, int) and fetched == requested
        and not coverage.get("missing")
    )
    scan_ok = (outcomes.get("scan") == "success" and isinstance(scan, dict)
               and isinstance(scan.get("candidates"), list) and bool(scan.get("as_of")))
    ready = scan_ok and all(
        outcomes.get(key) == "success"
        for key in ("read_state", "fetch", "resolve")
    )
    if not ready:
        return dict(scanner_status="DATA_GAP", scan_completed=False,
                    candidate_count=None, coverage_complete=complete)
    return dict(
        scanner_status="OBSERVED" if complete else "PARTIAL_OBSERVED",
        scan_completed=True,
        candidate_count=len(scan["candidates"]),
        as_of=scan["as_of"],
        state_published=outcomes.get("persist") == "success",
        coverage_complete=complete,
    )
