"""Automatic READ-ONLY discovery of US stocks up 5–10% from public Nasdaq screener.

Nasdaq listings offer screening, NOT timestamp-verified live quotes. This process
NEVER calls radar.ingest, FIRST_WATCH, or buy. Artifacts are discovery candidates.
"""
import argparse
import json
import math
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000"
MAX_BYTES = 15_000_000
MAX_CANDIDATES = 100

def percent(value):
    if isinstance(value, bool):
        return None
    s = str(value or "").strip().replace(",", "")
    s = s.replace("%", "").replace("+", "")
    try:
        p = float(s)
        return p if math.isfinite(p) else None
    except ValueError:
        return None

def get_rows(payload):
    if not isinstance(payload,dict):
        raise ValueError("Unexpected Nasdaq schema")
    block=payload.get("data")
    if not isinstance(block,dict):
        raise ValueError("Missing data object")
    rows=block.get("rows")
    if rows is None and isinstance(block.get("table"),dict):
        rows=block["table"].get("rows")
    if not isinstance(rows,list):
        raise ValueError("No listing rows; fail closed")
    return rows, block.get("totalRecords")

def find_candidates(rows):
    found=[]
    eligible=0
    malformed=0
    for row in rows:
        if not isinstance(row,dict):
            malformed+=1
            continue
        symbol=str(row.get("symbol") or "").strip().upper()
        change=percent(row.get("pctchange"))
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}",symbol) or change is None:
            malformed+=1
            continue
        eligible+=1
        if 5<=change<=10:
            found.append({
                "symbol":symbol,
                "reported_change_pct":round(change,4),
                "last_sale_text":str(row.get("lastsale") or ""),
                "name":str(row.get("name") or "")[:120],
                "classification":"UNVERIFIED_DISCOVERY_ONLY",
                "quote_source_timestamp":None,
                "eligible_for_first_watch":False
            })
    found.sort(key=lambda x:(-x["reported_change_pct"],x["symbol"]))
    return found[:MAX_CANDIDATES],eligible,malformed,len(found)

def fetch_payload(opener=None):
    opener = opener or urllib.request.urlopen
    req=urllib.request.Request(SOURCE,headers={
        "Accept":"application/json",
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "Referer":"https://www.nasdaq.com/",
    })
    with opener(req,timeout=20) as response:
        data=response.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:
        raise ValueError("Listing response too large")
    return json.loads(data)

def run(payload=None,at=None):
    at = at or datetime.now(timezone.utc)
    report={
        "checked_at_utc":at.isoformat(),
        "provider":"Nasdaq public screener",
        "mode":"SHADOW_DISCOVERY_ONLY",
        "trading_enabled":False,
        "valid_first_watch_signals":0,
        "source_timestamp_verified":False,
        "source_latency_verified":False,
        "run_retrieval_timestamp_is_not_a_quote_timestamp":True,
        "scan_status":"NO_DATA",
        "rows_received":0,
        "parseable_rows":0,
        "nasdaq_total_reported":None,
        "candidates_total":0,
        "candidates":[]
    }
    try:
        raw = fetch_payload() if payload is None else payload
        rows,total=get_rows(raw)
        found,parseable,malformed,actual_count=find_candidates(rows)
        report.update(scan_status="DISCOVERY_ONLY" if rows else "EMPTY_SOURCE",
            rows_received=len(rows),parseable_rows=parseable,malformed_rows=malformed,
            nasdaq_total_reported=total,candidates_total=actual_count,candidates=found)
        if isinstance(total,int) and total>len(rows):
            report["partial_universe"]=True
        else:
            report["partial_universe"]="UNKNOWN" if total is None else False
    except (ValueError,KeyError,TypeError,json.JSONDecodeError,urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError) as exc:
        report["scan_status"]="SOURCE_ERROR"
        report["error_type"]=type(exc).__name__
    return report

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default="radar-discovery.json")
    a=ap.parse_args()
    result=run()
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["scan_status"],
        "rows":result["rows_received"],
        "candidates":result["candidates_total"],
        "saved_candidates":len(result["candidates"]),
        "validated_signals":0}))

if __name__=="__main__":
    main()
