"""Non-executable BUY-CANDIDATE actionability audit.

This is NOT an order recommendation. It does not modify the immutable
SAG-30 v0.3.3 FROZEN SHADOW model or emit outbox alerts.
"""
import json
import math
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
VERSION="BUY_ACTIONABILITY_SHADOW_V1"
MAX_SOURCE_AGE_SECONDS=60
MAX_SPREAD_PCT=2.0
MAX_ASK_PREMIUM_PCT=3.0

def _age(retrieved, source):
    try:
        t=datetime.fromisoformat(retrieved.replace("Z","+00:00"))
        s=datetime.fromisoformat(source.replace("Z","+00:00"))
        if t.tzinfo is None or s.tzinfo is None: return None
        return (t-s).total_seconds()
    except (TypeError,ValueError,AttributeError):
        return None

def _positive(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0

def assess(snapshot, retrieval_ts, quality, change_pct, state):
    """Only same-snapshot quote and trade; never use future bars or next prints."""
    blockers=[]
    if quality!="OK": blockers.append("DATA_QUALITY")
    if state!="C34R2-HOT-SHADOW": blockers.append("NOT_EARLY_HOT_CANDIDATE")
    if not isinstance(change_pct,(int,float)) or change_pct>=20:
        blockers.append("LATE_OR_MISSING_PCT")
    try:
        t=datetime.fromisoformat(retrieval_ts.replace("Z","+00:00")).astimezone(ET)
        if not (t.weekday()<5 and (t.hour*60+t.minute)>=570 and (t.hour*60+t.minute)<960):
            blockers.append("OUTSIDE_REGULAR_SESSION")
    except (TypeError,ValueError):
        blockers.append("INVALID_RETRIEVAL_TS")
    trade=snapshot.get("latestTrade") or {}
    quote=snapshot.get("latestQuote") or {}
    trade_price=trade.get("p")
    trade_age=_age(retrieval_ts,trade.get("t"))
    quote_age=_age(retrieval_ts,quote.get("t"))
    if not _positive(trade_price) or trade_age is None or not 0<=trade_age<=MAX_SOURCE_AGE_SECONDS:
        blockers.append("MISSING_OR_STALE_TRADE")
    bid,ask=quote.get("bp"),quote.get("ap")
    bs,az=quote.get("bs"),quote.get("as")
    if quote_age is None or not 0<=quote_age<=MAX_SOURCE_AGE_SECONDS:
        blockers.append("MISSING_OR_STALE_QUOTE")
    spread=None
    premium=None
    if not (_positive(bid) and _positive(ask) and ask>=bid):
        blockers.append("INVALID_BID_ASK")
    else:
        spread=100*(ask-bid)/((ask+bid)/2)
        if spread>MAX_SPREAD_PCT:
            blockers.append("SPREAD_OVER_2_PCT")
        if _positive(trade_price):
            premium=100*(ask/trade_price-1)
            if premium>MAX_ASK_PREMIUM_PCT:
                blockers.append("ASK_PREMIUM_OVER_3_PCT")
    if not (_positive(bs) and _positive(az)):
        blockers.append("MISSING_TOP_OF_BOOK_SIZE")
    return {"status":"QUOTE_SCREEN_PASSED_SHADOW_NOT_BUY" if not blockers else "BLOCKED_SHADOW_NOT_BUY",
            "blockers":blockers,"trade_age_seconds":trade_age,"quote_age_seconds":quote_age,
            "spread_pct":round(spread,4) if spread is not None else None,
            "ask_premium_vs_last_trade_pct":round(premium,4) if premium is not None else None,
            "quote_bid":bid,"quote_ask":ask,
            "note":"Quote is indicative, not guaranteed fill. IEX top-of-book is not consolidated NBBO. No order execution, no BUY approval."}

def build(db):
    table=db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_v034r2_signals'"
    ).fetchone()
    if not table:
        return {"status":"NO_CANDIDATE_SIGNALS_TABLE","version":VERSION,"not_buy":True}
    rows=db.execute(
        "SELECT s.symbol,s.retrieval_ts,s.state,s.change_pct,o.quality,o.payload "
        "FROM candidate_v034r2_signals s JOIN observations o ON o.id=s.observation_id "
        "WHERE s.state='C34R2-HOT-SHADOW' ORDER BY s.retrieval_ts,s.id"
    ).fetchall()
    cases=[]; blockers=Counter();passed=0
    for symbol,ts,state,pct,quality,raw in rows:
        try:
            snap=json.loads(raw)
            if not isinstance(snap,dict): raise ValueError("snapshot not object")
        except (ValueError,TypeError):
            snap={}
        result=assess(snap,ts,quality,pct,state)
        passed+=int(result["status"]=="QUOTE_SCREEN_PASSED_SHADOW_NOT_BUY")
        blockers.update(result["blockers"])
        cases.append({"symbol":symbol,"retrieval_ts":ts,"change_pct":pct,**result})
    return {"version":VERSION,"status":"RESEARCH_SHADOW_NOT_BUY",
            "not_buy":True,"thresholds_research_only":{"max_quote_age_seconds":MAX_SOURCE_AGE_SECONDS,
            "max_trade_age_seconds":MAX_SOURCE_AGE_SECONDS,"max_spread_pct":MAX_SPREAD_PCT,
            "max_ask_premium_pct":MAX_ASK_PREMIUM_PCT},
            "candidate_signals":len(rows),"quote_screen_passed":passed,
            "quote_screen_blocked":len(rows)-passed,
            "blockers_nonexclusive":dict(sorted(blockers.items())),
            "cases":cases[-100:],
            "limitations":"No execution evidence, fill probability, full-market NBBO, trading costs or actual BUY. Missing quotes remain blocked; never infer spread from last trades. Frozen v0.3.3 is NOT BUY."}
