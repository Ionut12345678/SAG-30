"""Independent read-only production checkpoint restoration drill.

Uses existing lossless restore; verifies published WATCH journals against
the same commit's checkpoint manifest, without updating radar-state.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from radar.checkpoint import JOURNALS, MANIFEST, restore_git, validate_manifest


def git_file(repo, commit, name):
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{name}"])


def verify(repo, ref, output):
    commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--verify", ref + "^{commit}"],
        text=True).strip()
    manifest = json.loads(git_file(repo, commit, MANIFEST))
    validate_manifest(manifest)
    with TemporaryDirectory(prefix="sag30-drill-") as temp:
        dest = Path(temp) / "restored.sqlite3"
        counts = restore_git(repo, commit, dest)
    # Check the published source journals. Existing DB restore verifies the
    # compressed/deduplicated parts, total SHA, SQLite quick_check and row counts.
    declared = {entry["name"]: entry for entry in manifest.get("journals", [])}
    results = {}
    for name in JOURNALS:
        if name not in declared:
            results[name] = "NOT_DECLARED"
            continue
        payload = git_file(repo, commit, name)
        row = declared[name]
        if len(payload) != row["bytes"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValueError("Published journal checksum/size mismatch: " + name)
        results[name] = "SHA256_OK"
    result = {
        "status": "RESTORE_VERIFIED",
        "checkpoint_commit": commit,
        "workflow_run_id": manifest.get("workflow_run_id"),
        "database_sha256": manifest["database_sha256"],
        "table_count": len(counts),
        "row_count": sum(counts.values()),
        "journal_verification": results,
        "note": "Read-only integrity drill; does not prove recovery from a failed push or trading actionability.",
    }
    Path(output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default=".")
    p.add_argument("--ref", default="FETCH_HEAD")
    p.add_argument("--output", required=True)
    a = p.parse_args()
    print(json.dumps(verify(a.repo, a.ref, a.output), sort_keys=True))


if __name__ == "__main__":
    main()
