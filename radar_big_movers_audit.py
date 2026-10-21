"""Audit public Big Movers hindsight labels against annual daily proxy research.

IMPORTANT: This is a winners-only, hindsight-selected file, not a balanced
historical stock universe and not a stream of entry signals. Only retrospective
coverage diagnostics; does NOT influence BUY or the tested classifier.
"""
import argparse
import csv
import io
import json
import math
import re
import urllib.request
from collections import Counter
from pathlib import Path

SOURCE=("https://raw.githubusercontent.com/willhjw/big_movers/"
        "54d4ca613b78c7fc14e5d1067dc8d0671407896e/big_movers_result.csv")
MAX_BYTES=250000

def load_csv(data):
    rows=[]
    reader=csv.DictReader(io.StringIO(data.lstrip("\ufeff")))
    needed={"year","symbol","gain_pct","low_date","high_date"}
    if not reader.fieldnames or not needed.issubset(reader.fieldnames):
        raise ValueError("invalid big movers columns")
    for item in reader:
        try:
            year=int(item["year"])
            symbol=item["symbol"].strip().upper()
            gain=float(item["gain_pct"])
            lo=item["low_date"].strip()
            hi=item["high_date"].strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}",symbol):continue
            if not (math.isfinite(gain) and 0<=gain<=100000):continue
            if not (len(lo)==10 and len(hi)==10 and lo<=hi):continue
            if not (1900<=year<=2100):continue
            rows.append({"year":year,"symbol":symbol,"gain_pct":round(gain,2),
                         "low_date":lo,"high_date":hi})
        except (ValueError,TypeError,AttributeError,KeyError):
            continue
    return rows

def audit(labels,annual):
    symbols=annual.get("symbols",[]) if isinstance(annual,dict) else []
    tracked={s["symbol"] for s in symbols if isinstance(s,dict) and s.get("eligible") and isinstance(s.get("symbol"),str)}
    covered_years={r["year"] for r in labels}
    relevant=[r for r in labels if r["year"] in (2025,2026)]
    overlap=sorted({r["symbol"] for r in relevant if r["symbol"] in tracked})
    return {"status":"HINDSIGHT_LABEL_AUDIT_NOT_TRADING_SIGNAL",
            "source":SOURCE,"labels_count":len(labels),
            "unique_labeled_symbols":len({r["symbol"] for r in labels}),
            "years_in_public_file":[min(covered_years),max(covered_years)] if covered_years else [],
            "labels_2025_2026":len(relevant),"eligible_annual_daily_symbols":len(tracked),
            "overlapping_symbols":overlap,"overlap_count":len(overlap),
            "year_counts":dict(sorted(Counter(r["year"] for r in labels).items())),
            "sampling_warning":"Winner-only annual labels; no negative cases, no point-in-time screener",
            "forbidden_uses":["training early signal rules from hindsight winner label",
                              "calculating precision from positive-only data",
                              "claiming one-minute prices or executable fills"],
            "included_delisted_universe_verified":False,
            "trade_signals":0,"buy_enabled":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--annual",default="annual-daily-research.json")
    p.add_argument("--out",default="big-movers-audit.json")
    args=p.parse_args()
    try:annual=json.loads(Path(args.annual).read_text())
    except (OSError,ValueError):annual={}
    req=urllib.request.Request(SOURCE,headers={"Accept":"text/csv","User-Agent":"RadarNou-Research/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=15) as response:
            payload=response.read(MAX_BYTES+1)
        if len(payload)>MAX_BYTES:raise ValueError("oversized label file")
        labels=load_csv(payload.decode("utf-8-sig"))
        report=audit(labels,annual)
    except (OSError,ValueError,UnicodeError) as exc:
        report={"status":"SOURCE_UNAVAILABLE","error_type":type(exc).__name__,
                "source":SOURCE,"trade_signals":0,"buy_enabled":False}
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report.get(k) for k in ("status","labels_count","years_in_public_file",
                                                "labels_2025_2026","overlap_count","error_type")}))
if __name__=="__main__":main()
