"""Read-only checkpoint capacity and lossless-part structural diagnostics."""
import argparse
import json
import math
from pathlib import Path
from radar.checkpoint import BLOB_LIMIT, PART_BYTES, validate_manifest

MIB = 1024 * 1024


def diagnose(manifest, previous=None):
    problems = []
    try:
        validate_manifest(manifest)
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": "INVALID_MANIFEST", "reasons": ["MANIFEST_INVALID"],
                "detail": str(exc), "restore_verified": False}
    parts = manifest["parts"]
    maximum = max(x["bytes"] for x in parts)
    total = manifest["compressed_bytes"]
    if maximum >= BLOB_LIMIT:
        problems.append("PART_GIT_BLOB_LIMIT")
    if total >= 90*MIB:
        problems.append("TOTAL_COMPRESSED_GT_90_MIB")
    delta = None
    if previous is not None:
        try:
            validate_manifest(previous)
            delta = total-previous["compressed_bytes"]
        except (ValueError,KeyError,TypeError):
            problems.append("PREVIOUS_MANIFEST_INVALID")
    if delta is not None and delta > 0:
        problems.append("COMPRESSED_CHECKPOINT_GROWING")
    return {"status": "CAPACITY_WARNING" if problems else "STRUCTURAL_CHECK_PASS",
            "reasons": problems, "compressed_bytes_total": total,
            "compressed_growth_bytes_vs_previous": delta,
            "part_count":len(parts), "largest_part_bytes":maximum,
            "git_blob_limit_bytes":BLOB_LIMIT,
            "part_headroom_bytes":BLOB_LIMIT-maximum,
            "expected_next_part_count_at_64mib":math.ceil(total/PART_BYTES),
            "restore_verified":False,
            "source":"checkpoint manifests only; no downloaded part hash or SQLite restore verification",
            "note":"Large total != oversized Git blob. Growth still carries storage/quota risk. Never delete audit rows."}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--output", type=Path)
    a=ap.parse_args()
    data=json.loads(a.manifest.read_text())
    prior=json.loads(a.previous.read_text()) if a.previous and a.previous.is_file() else None
    result=diagnose(data,prior)
    payload=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if a.output:
        a.output.write_text(payload)
    print(payload)


if __name__=="__main__":
    main()
