"""Research-only prospective scan of timestamped public quotes.

No screening history is imported. Never places orders.
"""
import argparse
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from public_data_adapter import fetch
from prospective_ledger import append_event

def scan(symbols,ledger,now=None,interval="1m"):
    now=now or datetime.now(timezone.utc)
    report={"observed":0,"discovered":0,"validated":0,"rejected":0,"source_errors":[]}
    for symbol in symbols:
        try:
            bars=fetch(symbol,interval=interval,range_="5d")
            bars=sorted(bars,key=lambda x:x["source_ts"])
            current=[x for x in bars if x.get("close") is not None and x.get("volume") is not None]
            if len(current)<2:raise ValueError("insufficient timestamped bars")
            last=current[-1]
            stamp=datetime.fromisoformat(last["source_ts"])
            prior=[x for x in current if datetime.fromisoformat(x["source_ts"]).date()<stamp.date()]
            if not prior:raise ValueError("previous regular close unavailable")
            # Intraday chart bars are NOT proof of the previous regular session close.
            # Explicitly reject rather than guessing the reference from an intraday bar.
            raise ValueError("previous_regular_close_unverified")
        except Exception as exc:
            report["source_errors"].append({"symbol":symbol,"reason":str(exc)[:180]})
            report["rejected"]+=1
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--symbols",nargs="+",default=["AAPL","MSFT","NVDA","AMD","PLTR"])
    p.add_argument("--ledger",required=True)
    a=p.parse_args()
    print("PROSPECTIVE_SCAN",json.dumps(scan(a.symbols,a.ledger),sort_keys=True))
