"""Seven-day SHADOW-only Gate 0 evaluation: no trading, no model changes."""
import argparse
import datetime as dt
import json
from pathlib import Path

UTC = dt.timezone.utc


def parse(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def evaluate(state, recovery, runs, now, start, end):
    tracked = state.get("tracked", {})
    outcomes = recovery.get("outcomes", {})
    signals = []
    for symbol, item in sorted(tracked.items()):
        first = parse(item["first_seen"])
        if not start <= first < end:
            continue
        followup = outcomes.get(symbol, {})
        signals.append({
            "symbol": symbol, "first_seen": item["first_seen"],
            "first_price": item["first_price"],
            "observed_4h_max_pct": followup.get("max_pct_after"),
            "observed_4h_status": followup.get("status", "DATA_GAP"),
            "t_plus_1": "NOT_MEASURED", "t_plus_2": "NOT_MEASURED",
            "t_plus_5": "NOT_MEASURED",
            "execution_quality": "NOT_MEASURED",
        })
    observed = [s for s in signals if s["observed_4h_max_pct"] is not None]
    eligible = [r for r in runs if r.get("event") in ("schedule", "workflow_dispatch")
                and r.get("created_at") and start <= parse(r["created_at"]) < end]
    completed = [r for r in eligible if r.get("status") == "completed"]
    return {
        "mode": "SHADOW_ONLY", "buy": False, "gate": "HOLD",
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "as_of": now.isoformat(), "run_count": len(eligible),
        "completed_run_count": len(completed),
        "cadence_coverage_pct": None,
        "cadence_note": "No PASS without an independently verified market-session slot denominator",
        "signals": signals, "signal_count": len(signals),
        "followup_coverage_pct": round(100 * len(observed) / len(signals), 2) if signals else None,
        "confirmed_4h_plus_20": sum(s["observed_4h_max_pct"] >= 20 for s in observed),
        "t_plus_1_2_5_complete": False,
        "matched_control_complete": False,
        "pass_criteria": {"scan_coverage_min_pct": 95, "complete_t_plus_1_2_5": True,
                          "outperform_matched_control": True},
        "verdict_reason": "Cadence denominator, multi-day follow-up and matched control not yet validated",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--recovery", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--start", default="2026-10-16T00:00:00+00:00")
    parser.add_argument("--end", default="2026-10-23T00:00:00+00:00")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    now = dt.datetime.now(UTC)
    result = evaluate(json.loads(Path(args.state).read_text()),
                      json.loads(Path(args.recovery).read_text()),
                      json.loads(Path(args.runs).read_text()),
                      now, parse(args.start), parse(args.end))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
