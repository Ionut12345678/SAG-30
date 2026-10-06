import sqlite3
from datetime import datetime, timedelta, timezone

from radar.fast_path_shadow import init, evaluate_one

def test_event_path_can_trigger_but_never_buy():
    db=sqlite3.connect(":memory:")
    init(db)
    now=datetime(2026,10,6,14,0,tzinfo=timezone.utc)
    a=evaluate_one(db,"2026-10-06","TEST","EVENT",["CONTRACT"],(10.2,2.0,1000,"2026-10-06T14:00:00Z"),now)
    assert a["state"]=="PREARM_EVENT"
    b=evaluate_one(db,"2026-10-06","TEST","EVENT",["CONTRACT"],(10.5,3.0,1300,"2026-10-06T14:01:00Z"),now+timedelta(minutes=1))
    assert b["state"]=="TRIGGER_SHADOW"
    assert "BUY" not in b["state"]

def test_flow_requires_persistence():
    db=sqlite3.connect(":memory:")
    init(db)
    now=datetime(2026,10,6,14,0,tzinfo=timezone.utc)
    evaluate_one(db,"2026-10-06","FLOW","WATCHPOOL",[],(10.0,1.0,1000,"2026-10-06T14:00:00Z"),now)
    a=evaluate_one(db,"2026-10-06","FLOW","WATCHPOOL",[],(10.2,2.0,1300,"2026-10-06T14:01:00Z"),now+timedelta(minutes=1))
    assert a["state"]=="DISCOVERED"
    b=evaluate_one(db,"2026-10-06","FLOW","WATCHPOOL",[],(10.4,3.0,1700,"2026-10-06T14:02:00Z"),now+timedelta(minutes=2))
    assert b["state"]=="TRIGGER_SHADOW"

def test_twenty_percent_is_late():
    db=sqlite3.connect(":memory:")
    init(db)
    now=datetime(2026,10,6,14,0,tzinfo=timezone.utc)
    r=evaluate_one(db,"2026-10-06","LATE","EVENT",["MNA"],(12.0,25.0,5000,"2026-10-06T14:00:00Z"),now)
    assert r["state"]=="LATE_SHADOW"
