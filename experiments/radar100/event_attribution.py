"""Point-in-time event join for Radar100. Requires real timestamped event CSV.
No fabricated headlines, no future data, no trading.
CSV fields: symbol,published_at_utc,event_type,source_url
"""
import argparse,csv,json
from datetime import datetime,timezone,timedelta
from pathlib import Path

def parse_time(value):
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:raise ValueError("Event timestamp must include UTC offset")
    return dt.astimezone(timezone.utc)

def associate(signals,events,max_age_days=7):
    if not 0<=max_age_days<=30:raise ValueError("Bad max age")
    output=[]
    for s in signals:
        # Trading-day signal is generated after regular close at 16:00 New York.
        # Conservative cut-off at 20:00 UTC would exclude late-day ET news in winter;
        # use timezone-aware NY session close instead.
        from zoneinfo import ZoneInfo
        ny=ZoneInfo("America/New_York")
        close=datetime.fromisoformat(s["signal_date"]+"T16:00:00").replace(tzinfo=ny).astimezone(timezone.utc)
        eligible=[]
        for event in events:
            if event["symbol"].upper()!=s["symbol"].upper():continue
            t=parse_time(event["published_at_utc"])
            if close-timedelta(days=max_age_days)<=t<=close:
                eligible.append({"event_type":event["event_type"],"published_at_utc":event["published_at_utc"],
                                 "source_url":event["source_url"]})
        output.append({"signal_id":s["id"],"symbol":s["symbol"],"signal_date":s["signal_date"],
                       "known_event_count":len(eligible),"known_events":sorted(eligible,key=lambda x:x["published_at_utc"])})
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",required=True);p.add_argument("--events",required=True);p.add_argument("--out",required=True)
    a=p.parse_args()
    ledger=json.loads(Path(a.state).read_text(encoding="utf-8"))
    with open(a.events,newline="",encoding="utf-8") as f:events=list(csv.DictReader(f))
    required={"symbol","published_at_utc","event_type","source_url"}
    for e in events:
        if not required.issubset(e) or any(not e[k] for k in required):
            raise ValueError("Event CSV has missing required fields")
        if not e["source_url"].startswith(("https://","http://")):raise ValueError("Event needs source URL")
    output=associate(ledger["signals"],events)
    Path(a.out).write_text(json.dumps({"events_supplied":len(events),"associations":output},indent=2)+"\n")
    print(f"Events supplied={len(events)} matched signals={sum(x['known_event_count']>0 for x in output)}")
if __name__=="__main__":main()
