"""Read-only prospective US regular-session quote probe; no orders."""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from public_data_adapter import fetch
from prospective_ledger import append_event

NY=ZoneInfo("America/New_York")

def previous_close(daily,local_day):
    eligible=[r for r in daily if r.get("close") and datetime.fromisoformat(r["source_ts"]).astimezone(NY).date()<local_day]
    if not eligible:raise ValueError("previous_regular_close_unavailable")
    return float(eligible[-1]["close"])

def scan(symbols,ledger,now=None):
    now=now or datetime.now(timezone.utc)
    report={"observed":0,"discovered":0,"validated":0,"rejected":0,"source_errors":[]}
    for symbol in symbols:
        try:
            bars=fetch(symbol,interval="1m",range_="5d")
            daily=fetch(symbol,interval="1d",range_="1mo")
            if not bars or not daily:raise ValueError("empty_source")
            eligible=[r for r in bars if datetime.fromisoformat(r["source_ts"]) + timedelta(minutes=1) <= now]
            if not eligible:raise ValueError("no_completed_intraday_bar")
            quote=max(eligible,key=lambda r:r["source_ts"])
            src=datetime.fromisoformat(quote["source_ts"]) + timedelta(minutes=1)
            local=src.astimezone(NY)
            if not (local.weekday()<5 and (local.hour,local.minute)>=(9,30) and (local.hour,local.minute)<(16,0)):
                raise ValueError("outside_regular_session")
            reference=previous_close(daily,local.date())
            if now-src<timedelta(0):raise ValueError("future_source_timestamp")
            price=float(quote["close"])
            volume=quote.get("volume")
            change=100*(price/reference-1)
            quality="validated" if timedelta(0)<=now-src<=timedelta(minutes=5) and volume is not None and volume>0 else "stale_or_missing_volume"
            event={"symbol":symbol,"first_seen":now.isoformat(),"provider":quote["provider"],
                "source_ts":src.isoformat(),"price":price,"previous_regular_close":reference,
                "volume":volume,"data_quality":quality,"kind":"discovery"}
            report["observed"]+=1
            if not (3<=change<=10):
                report["rejected"]+=1
                continue
            prior = [json.loads(s) for s in Path(ledger).read_text().splitlines() if s.strip()] if Path(ledger).exists() else []
            if not any(x["symbol"] == symbol and x["kind"] == "discovery" for x in prior):
                if append_event(ledger,event):report["discovered"]+=1
            if quality=="validated":
                valid={**event,"kind":"validated_signal"}
                if append_event(ledger,valid):report["validated"]+=1
            else:report["rejected"]+=1
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
