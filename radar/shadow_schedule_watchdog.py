"""Best-effort SHADOW Lite cron watchdog. Never places trades."""
import datetime as dt
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc


def market_window(now):
    local = now.astimezone(ZoneInfo("America/New_York"))
    return local.weekday() < 5 and dt.time(9, 35) <= local.time().replace(tzinfo=None) < dt.time(16, 0)


def needs_recovery(runs, now, stale_minutes=15):
    """Count queued, running and completed runs; do not dispatch duplicates."""
    for run in runs:
        if run.get("event") not in ("schedule", "workflow_dispatch"):
            continue
        try:
            created = dt.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            continue
        age = (now - created).total_seconds()
        if run.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"):
            return False
        if -120 <= age <= stale_minutes * 60:
            return False
    return True


def api(url, token, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "sag30-shadow-watchdog",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read()) if method == "GET" else {}


def main():
    now = dt.datetime.now(UTC)
    result = {"checked_at": now.isoformat(), "mode": "SHADOW_ONLY",
              "market_window": market_window(now), "dispatched": False}
    if not result["market_window"]:
        result["reason"] = "OUTSIDE_WINDOW"
    else:
        repo = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GH_TOKEN"]
        base = f"https://api.github.com/repos/{repo}"
        runs = api(base + "/actions/workflows/shadow-lite.yml/runs?branch=main&per_page=30",
                   token).get("workflow_runs", [])
        result["runs_checked"] = len(runs)
        if needs_recovery(runs, now):
            # A missed schedule is recoverable only prospectively; no historical data is invented.
            api(base + "/actions/workflows/shadow-lite.yml/dispatches", token, "POST",
                {"ref": "main"})
            result["dispatched"] = True
            result["reason"] = "STALE_SCHEDULE_RECOVERY"
        else:
            result["reason"] = "RECENT_RUN_EXISTS"
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "WATCHDOG_ERROR", "error_type": type(exc).__name__}), file=sys.stderr)
        raise
