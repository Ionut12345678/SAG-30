"""Forward-only WATCH outcome ledger. Research only, no BUY/price execution."""
import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def stamp(value):
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (AttributeError, ValueError, TypeError):
        return None


def valid_pct(value):
    try:
        p = float(value)
        return p if math.isfinite(p) and p > -100 else None
    except (ValueError, TypeError):
        return None


def read_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def build(watches, observations, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc)
    obs = defaultdict(dict)
    for item in observations:
        ts = stamp(item.get("ts"))
        pct = valid_pct(item.get("change_pct"))
        if ts is None or pct is None:
            continue
        key = (item.get("session"), item.get("symbol"))
        # Duplicate timestamps are not independently observed outcomes.
        obs[key].setdefault(ts, pct)
    cases = []
    seen = set()
    for watch in watches:
        key = (watch.get("session"), watch.get("symbol"))
        if key in seen:
            continue
        seen.add(key)
        wts = stamp(watch.get("ts"))
        entry = valid_pct(watch.get("change_pct"))
        if wts is None or entry is None:
            continue
        # No credit for the watch snapshot itself; strictly later observations.
        future = sorted((t, p) for t, p in obs[key].items() if t > wts and t <= generated_at)
        peak_ts, peak_pct = max(future, key=lambda x:x[1]) if future else (None, None)
        last_ts, last_pct = future[-1] if future else (None, None)
        def milestone(target):
            return next(((t, p) for t, p in future if p >= target), (None, None))
        milestones = {}
        for target in (15, 20, 30, 50):
            mt, mp = milestone(target)
            milestones[str(target)] = {
                "ts": mt.isoformat() if mt else None,
                "observed_pct": mp,
                "minutes_after_watch": round((mt-wts).total_seconds()/60, 2) if mt else None,
                "qualifies_post_watch": bool(mt) and entry < target,
            }
        cases.append({
            "session": key[0], "symbol": key[1], "first_watch_ts": wts.isoformat(),
            "first_watch_pct": entry,
            "future_observation_count": len(future),
            "status": "OBSERVED_FOLLOWUP" if future else "NO_LATER_OBSERVATION",
            "last_observed_ts": last_ts.isoformat() if last_ts else None,
            "last_observed_pct": last_pct,
            "peak_observed_ts": peak_ts.isoformat() if peak_ts else None,
            "peak_observed_pct": peak_pct,
            "max_pp_from_watch": round(peak_pct-entry, 5) if peak_pct is not None else None,
            "max_pct_return_from_watch_reference": round(
                100*((100+peak_pct)/(100+entry)-1), 5) if peak_pct is not None else None,
            "milestones": milestones,
            "execution_verified": False,
            "signal": "WATCH_ONLY_NOT_BUY"
        })
    cases.sort(key=lambda c: (c["session"], c["first_watch_ts"], c["symbol"]))
    return {"status":"PROSPECTIVE_SHADOW_NOT_BUY", "generated_at_utc":generated_at.isoformat(),
            "source":"persisted WATCH + later retrieval-time scout observations",
            "limitations":"Not exchange-executable highs; incomplete IEX/scout coverage; missing follow-ups are UNKNOWN, not failures. No BUY or fills.",
            "watch_count":len(cases), "with_later_observation":sum(c["future_observation_count"]>0 for c in cases),
            "verified_post_watch_30":sum(c["milestones"]["30"]["qualifies_post_watch"] for c in cases),
            "verified_post_watch_50":sum(c["milestones"]["50"]["qualifies_post_watch"] for c in cases),
            "cases":cases}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    report = build(read_jsonl(a.state_dir/"shadow_first_watch.jsonl"),
                   read_jsonl(a.state_dir/"shadow_watch_observations.jsonl"))
    out = a.out or a.state_dir/"forward_watch_outcomes.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="cases"}, sort_keys=True))


if __name__ == "__main__":
    main()
