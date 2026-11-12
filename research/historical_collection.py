"""Read-only historical Alpaca minute bars. Research/SHADOW only.

Never request live SIP. Use closed sessions and a 20-minute safety cutoff.
API keys are read from environment at execution time, never stored in Git.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://data.alpaca.markets/v2/stocks/bars"


def collect_bars(symbols, start, end, *, feed="sip", get=None, now=None,
                 max_pages=100, pause_seconds=0.25):
    """Return (bars_by_symbol, provenance). Fail closed on any missing page.

    start/end must be timezone-aware datetime objects. End must be older than
    20 minutes for SIP research; this restriction applies to both feeds.
    """
    if feed not in ("sip", "iex"):
        raise ValueError("unsupported feed")
    if not symbols or any(not s.isascii() or not s.replace(".", "").isalpha() for s in symbols):
        raise ValueError("invalid symbols")
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("invalid UTC-aware interval")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or end > now - timedelta(minutes=20):
        raise ValueError("historical-only cutoff: end must be >=20 minutes old")
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if get is None and (not key or not secret):
        raise RuntimeError("Alpaca API credentials missing")
    headers = {"APCA-API-KEY-ID": key or "", "APCA-API-SECRET-KEY": secret or ""}
    def http(url):
        request = Request(url, headers=headers)
        with urlopen(request, timeout=25) as response:
            return json.load(response)
    get = get or http
    output = {s: [] for s in symbols}
    cursor = None
    seen = set()
    pages = 0
    while True:
        if pages >= max_pages:
            raise RuntimeError("pagination limit exceeded; results incomplete")
        params = {"symbols": ",".join(symbols), "timeframe": "1Min",
                  "start": start.astimezone(timezone.utc).isoformat(),
                  "end": end.astimezone(timezone.utc).isoformat(),
                  "feed": feed, "limit": 10000, "sort": "asc"}
        if cursor:
            params["page_token"] = cursor
        try:
            payload = get(BASE + "?" + urlencode(params))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError("Alpaca historical request failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
            raise RuntimeError("invalid Alpaca bars response")
        for symbol, bars in payload["bars"].items():
            if symbol not in output or not isinstance(bars, list):
                raise RuntimeError("unexpected symbol/bars")
            output[symbol].extend(bars)
        pages += 1
        token = payload.get("next_page_token")
        if not token:
            break
        if token in seen:
            raise RuntimeError("pagination loop detected")
        seen.add(token)
        cursor = token
        if pause_seconds:
            time.sleep(pause_seconds)
    return output, {"feed": feed, "source": "alpaca", "timeframe": "1Min",
                    "start_utc": start.astimezone(timezone.utc).isoformat(),
                    "end_utc": end.astimezone(timezone.utc).isoformat(),
                    "retrieval_utc": now.astimezone(timezone.utc).isoformat(),
                    "pages": pages, "mode": "RETROSPECTIVE_SHADOW_NOT_LIVE"}
