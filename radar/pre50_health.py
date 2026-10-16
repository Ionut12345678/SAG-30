"""Explicit PRE50 health evidence; no trading or inferred candidates."""
import json
import os
from pathlib import Path


def classify(coverage, outcomes, scan=None):
    requested, fetched = coverage.get("requested"), coverage.get("fetched")
    counts_valid = (type(requested) is int and requested > 0
                    and type(fetched) is int and 0 <= fetched <= requested)
    coverage_complete = bool(counts_valid and fetched == requested and not coverage.get("missing"))
    scan_completed = (outcomes.get("scan") == "success"
                      and isinstance(scan, dict)
                      and isinstance(scan.get("candidates"), list)
                      and isinstance(scan.get("as_of"), str)
                      and bool(scan["as_of"]))
    prerequisites = all(outcomes.get(step) == "success"
                        for step in ("read_state", "fetch", "resolve", "scan"))
    valid = bool(counts_valid and fetched > 0 and scan_completed and prerequisites)
    status = ("OBSERVED" if coverage_complete else "PARTIAL_OBSERVED") if valid else "DATA_GAP"
    return {
        "scanner_status": status,
        "scan_completed": valid,
        "candidate_count": len(scan["candidates"]) if valid else None,
        "coverage_complete": coverage_complete,
        "state_published": outcomes.get("persist") == "success",
        "as_of": scan.get("as_of") if valid else None,
        # The current pipeline does not prove the last daily bar is a CLOSED session.
        "session_complete_verified": bool(valid and scan.get("session_complete_verified") is True),
        "reason": None if valid else ("SCAN_NOT_COMPLETED_OR_INVALID" if not scan_completed
                                      else "INCOMPLETE_PIPELINE_OR_COVERAGE"),
    }


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def write_health(directory, outcomes, run_id=None):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    coverage = load_json(folder / "coverage.json")
    scan = load_json(folder / "scan.json")
    coverage = coverage if isinstance(coverage, dict) else {}
    result = classify(coverage, outcomes, scan)
    result.update(run_id=run_id, mode="SHADOW_ONLY", buy=False,
                  outcomes=outcomes, coverage=coverage)
    (folder / "health.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    outcomes = {name: os.environ.get(name.upper() + "_OUTCOME", "unknown")
                for name in ("read_state", "fetch", "resolve", "scan", "persist")}
    print(json.dumps(write_health("pre50-out", outcomes, os.environ.get("GITHUB_RUN_ID")),
                     sort_keys=True))
