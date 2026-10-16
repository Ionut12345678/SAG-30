"""Read-only GitHub Actions pagination and Gate 0 cadence evidence."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from radar.gate0_cadence import audit

UTC = dt.timezone.utc


def collect(fetch_page, start, end):
    """Fetch all relevant pages; do not mistake truncated results for complete coverage."""
    rows = []
    page = 1
    while True:
        payload = fetch_page(page)
        batch = payload.get("workflow_runs", [])
        rows.extend(batch)
        if not batch:
            break
        if len(batch) < 100:
            break
        page += 1
        if page > 100:
            raise RuntimeError("Pagination exceeds 100 pages: cannot certify completeness")
    return [r for r in rows if r.get("created_at") and
            start <= dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < end]


def github_page(repo, token, page):
    params = urllib.parse.urlencode({"branch": "main", "per_page": 100, "page": page})
    url = f"https://api.github.com/repos/{repo}/actions/workflows/shadow-lite.yml/runs?{params}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "sag30-gate0-audit"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2026-10-16T00:00:00+00:00")
    p.add_argument("--end", default="2026-10-23T00:00:00+00:00")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    start = dt.datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    end = min(dt.datetime.fromisoformat(args.end.replace("Z", "+00:00")), dt.datetime.now(UTC))
    if end <= start:
        raise SystemExit("Window not yet started")
    runs = collect(lambda page: github_page(os.environ["GITHUB_REPOSITORY"],
                    os.environ["GH_TOKEN"], page), start, end)
    result = audit(runs, start, end)
    result.update({"window_start": start.isoformat(), "window_end": end.isoformat(),
                   "source": "github_actions_api", "fetched_runs": len(runs),
                   "gate": "HOLD", "mode": "SHADOW_ONLY",
                   "note": "Calendar holidays and early closes unverified; cannot PASS"})
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
