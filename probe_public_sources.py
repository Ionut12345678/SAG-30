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
    "yahoo_chart": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1m",
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
        elif name == "yahoo_chart":
            results = ((payload.get("chart") or {}).get("result") or []) if isinstance(payload,dict) else []
            meta = results[0].get("meta",{}) if results and isinstance(results[0],dict) else {}
            price = meta.get("regularMarketPrice")
            previous = meta.get("chartPreviousClose")
            epoch = meta.get("regularMarketTime")
            if not all(isinstance(v,(float,int)) and v>0 for v in (price,previous,epoch)):
                evidence["status"] = "SCHEMA_UNSUPPORTED"
                return evidence
            source_dt = datetime.fromtimestamp(epoch,timezone.utc)
            age = (datetime.now(timezone.utc)-source_dt).total_seconds()
            evidence["records"] = 1
            evidence["example_symbols"] = [str(meta.get("symbol","AAPL"))]
            evidence["source_ts"] = source_dt.isoformat()
            evidence["source_age_seconds"] = round(age,1)
            evidence["has_previous_close"] = True
            evidence["has_price"] = True
            evidence["source_timestamp_verified"] = False
            evidence["status"] = "TIMESTAMPED_RECENT_UNVERIFIED" if 0<=age<=120 else "TIMESTAMPED_STALE_OR_FUTURE"
            evidence["reason"] = "Unofficial Yahoo endpoint: price update timestamp exists but exchange latency, redistribution rights and full-universe coverage not verified"
            return evidence
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
        "interpretation": "Connectivity-only. A vendor timestamp is not proof of live venue trade, authoritative price or licensed universe coverage. Zero FIRST_WATCH.",
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sources": {r["source"]: r["status"] for r in results}, "signals_emitted": 0}))

if __name__ == "__main__":
    main()
