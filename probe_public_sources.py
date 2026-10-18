"""Read-only public market-data connectivity probe; NEVER qualifies BUY or FIRST_WATCH.

Public website endpoints are not licensed real-time feeds. Missing per-trade
source timestamps are treated as UNKNOWN, not replaced with retrieval time.
"""
import argparse
import csv
import io
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    "nasdaq_screener": "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10",
    "stockprices_dev": "https://stockprices.dev/api/stocks/AAPL",
    "stooq_quote": "https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcvnp&h&e=csv",
}
MAX_BYTES = 1_000_000

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def probe_one(name, url, opener=None):
    open_url = opener or urllib.request.urlopen
    evidence = {
        "source": name, "checked_at": now_utc(), "url": url,
        "market_price_authoritative": False, "prospective_signal_eligible": False,
        "source_timestamp_verified": False, "status": "NO_DATA",
        "records": 0,
    }
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "RadarNouResearch/0.5 (+read-only diagnostics)"})
    try:
        with open_url(request, timeout=12) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                evidence["status"] = "OVERSIZE"
                return evidence
            payload = list(csv.DictReader(io.StringIO(data.decode('utf-8')))) if name == 'stooq_quote' else json.loads(data)
        if name == "nasdaq_screener":
            block = (payload.get("data") or {}) if isinstance(payload, dict) else {}
            rows = block.get("rows")
            if rows is None:
                rows = (block.get("table") or {}).get("rows")
            if not isinstance(rows, list):
                evidence["status"] = "SCHEMA_UNSUPPORTED"
                return evidence
            evidence["records"] = len(rows)
            evidence["example_symbols"] = [str(r.get("symbol")) for r in rows[:5] if isinstance(r,dict) and r.get("symbol")]
        elif name == "stockprices_dev":
            if not isinstance(payload, dict) or payload.get("Price") is None:
                evidence["status"] = "SCHEMA_UNSUPPORTED"
                return evidence
            evidence["records"] = 1
            evidence["example_symbols"] = [str(payload.get("Ticker", "AAPL"))]
        elif name == "stooq_quote":
            if not isinstance(payload, list) or not payload or not any("Close" in r or "close" in r for r in payload):
                evidence["status"] = "SCHEMA_UNSUPPORTED"
                return evidence
            evidence["records"] = len(payload)
            evidence["example_symbols"] = [str(payload[0].get("Symbol","AAPL.US"))]
        else:
            evidence["status"] = "SOURCE_UNSUPPORTED"
            return evidence
        evidence["status"] = "REACHABLE_UNTIMESTAMPED" if evidence["records"] else "EMPTY"
        evidence["reason"] = "Response does not supply independently verified trade timestamp and previous regular close"
    except urllib.error.HTTPError as exc:
        evidence["status"] = "HTTP_ERROR"
        evidence["http_status"] = exc.code
    except urllib.error.URLError:
        evidence["status"] = "NETWORK_ERROR"
    except (ValueError, TypeError, OSError, TimeoutError):
        evidence["status"] = "PARSE_OR_IO_ERROR"
    return evidence

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="source-evidence.json")
    args = p.parse_args()
    results = [probe_one(name,url) for name,url in SOURCES.items()]
    report = {
        "checked_at": now_utc(), "mode": "SHADOW_ONLY", "orders_enabled": False,
        "market_closed_or_live_unknown": True,
        "valid_signals": None,
        "source_evidence": results,
        "interpretation": "Connectivity-only. No source has demonstrated <=120s per-trade freshness. No FIRST_WATCH emitted.",
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sources": {r["source"]: r["status"] for r in results}, "signals_emitted": 0}))

if __name__ == "__main__":
    main()
