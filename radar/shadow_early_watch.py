"""SHADOW-only permissive early candidate screen; no BUY and no production changes.

A screening rule uses only the current and past observations. It deliberately
maximizes discovery coverage; its precision must be measured on losers too.
"""
import math
from datetime import datetime, timezone

def _time(s):
    try:
        t=datetime.fromisoformat(s.replace("Z","+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (TypeError,ValueError,AttributeError):
        return None

def screen(observations):
    """Chronological [{ts,change_pct}]. Return earliest research watch trigger.

    Broad 3 lanes: price >= +3%; >= +2% 5-minute momentum; >= +5%
    10-minute momentum. All are OR triggers, never BUY decisions.
    """
    rows=[]
    for row in observations:
        t=_time(row.get("ts"))
        try:
            pct=float(row["change_pct"])
        except (TypeError,ValueError,KeyError):
            continue
        if t and math.isfinite(pct) and pct > -100:
            rows.append((t,pct))
    rows.sort()
    for i,(t,pct) in enumerate(rows):
        triggers=[]
        if pct>=3:
            triggers.append("PRICE_3")
        past=[(prior,p) for prior,p in rows[:i] if 1 <= (t-prior).total_seconds() <= 600]
        if past:
            for minutes,threshold,name in [(5,2,"MOMENTUM_5M_2"),(10,5,"MOMENTUM_10M_5")]:
                eligible=[(prior,p) for prior,p in past if (t-prior).total_seconds()<=minutes*60]
                if eligible and max(100*((100+pct)/(100+p)-1) for _,p in eligible)>=threshold:
                    triggers.append(name)
        if triggers:
            return {"status":"SHADOW_WATCH_ONLY","first_watch_ts":t.isoformat(),
                    "first_watch_change_pct":pct,"trigger_lanes":triggers,
                    "warning":"No liquidity, NBBO, catalyst or fill validation; not a BUY."}
    return {"status":"NO_WATCH","warning":"Absence of a watch is not a negative outcome."}
