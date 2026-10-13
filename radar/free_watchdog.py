"""Read-only SAG-30 health gate. Never dispatches or rewrites persisted state."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from .cadence import observation_window


def evaluate(health, now, max_age_seconds=1200):
    problems = []
    generated = health.get("generated_ts")
    if not generated:
        problems.append("MISSING_HEARTBEAT_TIMESTAMP")
    else:
        try:
            stamp = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("naive timestamp")
            age = (now - stamp.astimezone(timezone.utc)).total_seconds()
            if age > max_age_seconds:
                problems.append("STALE_HEARTBEAT")
            if age < -120:
                problems.append("FUTURE_HEARTBEAT")
        except (ValueError, TypeError):
            problems.append("INVALID_HEARTBEAT_TIMESTAMP")
    if health.get("health") not in ("PASS", "OK", "HEALTHY"):
        problems.append("NON_HEALTHY_REPORTED")
    checkpoint = health.get("checkpoint") or {}
    if checkpoint.get("part_count", 0) < 1:
        problems.append("CHECKPOINT_PARTS_UNKNOWN")
    if checkpoint.get("size_status") in ("CRITICAL_90_MIB", "OVER_LIMIT"):
        problems.append("CHECKPOINT_SIZE_WARNING")
    cadence = health.get("cadence") or {}
    if cadence.get("status") == "MISSED_TARGET":
        problems.append("CADENCE_MISSED_TARGET")
    scout = health.get("fast_scout") or {}
    if scout.get("status") != "PASS":
        problems.append("FAST_SCOUT_NOT_PASS")
    return {"status": "WARN" if problems else "PASS",
            "reasons": problems, "generated_ts": generated,
            "evidence_scope": "STORED_HEALTH_ONLY",
            "note": "Diagnostic only: no retry, BUY, checkpoint mutation, or historical promotion."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-age-seconds", type=int, default=1200)
    parser.add_argument("--fail-on-active-warning", action="store_true")
    args = parser.parse_args()
    if not args.health.exists():
        result = {"status": "WARN", "reasons": ["HEALTH_FILE_MISSING"],
                  "evidence_scope": "STORED_HEALTH_ONLY"}
    else:
        try:
            payload = json.loads(args.health.read_text(encoding="utf-8"))
            result = evaluate(payload, datetime.now(timezone.utc), args.max_age_seconds)
        except (json.JSONDecodeError, UnicodeError, OSError):
            result = {"status": "WARN", "reasons": ["HEALTH_FILE_INVALID"],
                      "evidence_scope": "STORED_HEALTH_ONLY"}
    serialized = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    if args.fail_on_active_warning and observation_window(datetime.now(timezone.utc)) and result['status'] == 'WARN':
        print('::error::SAG30_WATCHDOG_WARNING: ' + ','.join(result['reasons']))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
