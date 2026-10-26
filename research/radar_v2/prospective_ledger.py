"""Read-only prospective evidence ledger for Radar v2.

Append-only JSONL on a persistent volume. This module never submits orders.
Do not merge replay/historical records into the prospective ledger.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

def _instant(value):
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)

def append_event(path, event):
    required=("symbol","first_seen","provider","source_ts","price","previous_regular_close","volume","data_quality","kind")
    missing=[k for k in required if k not in event]
    if missing: raise ValueError("missing: "+",".join(missing))
    if event["kind"] not in ("discovery","validated_signal","followup","rejection"):
        raise ValueError("invalid kind")
    for key in ("first_seen","source_ts"):
        stamp=datetime.fromisoformat(event[key].replace("Z","+00:00"))
        if stamp.tzinfo is None:raise ValueError("timezone required")
    if event.get("mode","prospective")!="prospective":
        raise ValueError("replay forbidden in prospective ledger")
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    existing=[json.loads(x) for x in target.read_text().splitlines() if x.strip()] if target.exists() else []
    if event["kind"] in ("validated_signal","followup") and not existing:
        raise ValueError("no previous state; cannot validate or attribute followups")
    identity=(event["kind"],event["symbol"],event["provider"],event["source_ts"],event["price"])
    if any((x["kind"],x["symbol"],x["provider"],x["source_ts"],x["price"])==identity for x in existing):
        return False
    earliest=[x["first_seen"] for x in existing if x["symbol"]==event["symbol"] and x["kind"]=="discovery"]
    if event["kind"]=="discovery" and earliest and _instant(event["first_seen"])>min(_instant(x) for x in earliest):
        raise ValueError("duplicate discovery; preserve original first_seen")
    if event["kind"]=="validated_signal":
        if event["data_quality"]!="validated":
            raise ValueError("validated signal requires validated data quality")
        if not any(x["kind"]=="discovery" and x["symbol"]==event["symbol"] and _instant(x["first_seen"])<=_instant(event["first_seen"]) for x in existing):
            raise ValueError("validated signal requires prior recorded discovery")
    if event["kind"]=="followup":
        origins=[x for x in existing if x["symbol"]==event["symbol"] and x["kind"]=="validated_signal"]
        if not origins:raise ValueError("followup requires validated signal")
        if not any(_instant(event["source_ts"])>_instant(x["source_ts"]) and _instant(event["first_seen"])>_instant(x["first_seen"]) for x in origins):
            raise ValueError("followup must be strictly later than first_seen and source timestamp")
    with target.open("a",encoding="utf-8") as stream:
        stream.write(json.dumps({**event,"mode":"prospective"},sort_keys=True)+"\n")
    return True
