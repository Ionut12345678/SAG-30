"""Research-only BUY readiness funnel; never emits executable BUY.

Explicitly distinguishes discovery, quote actionability, and unvalidated edge.
"""
from radar.buy_actionability_shadow import assess

VERSION="BUY_READINESS_SHADOW_V1"

def evaluate(snapshot,retrieval_ts,quality,change_pct,state,discovery,priority):
    """Evaluate contemporaneous quote without converting research into an order."""
    discovered=bool(discovery)
    queue="PRIORITY" if discovered and priority else "DISCOVERY" if discovered else "NOT_DISCOVERED"
    screen=assess(snapshot,retrieval_ts,quality,change_pct,state)
    quote_pass=screen["status"]=="QUOTE_SCREEN_PASSED_SHADOW_NOT_BUY"
    blockers=list(screen["blockers"])
    if not discovered:blockers.insert(0,"NOT_IN_DISCOVERY_LANE")
    if not quote_pass:stage="BLOCKED_ACTIONABILITY"
    elif not discovered:stage="QUOTE_PASS_NOT_DISCOVERED"
    else:stage="ENTRY_READY_SHADOW_UNVALIDATED"
    return {"version":VERSION,"stage":stage,"queue":queue,
     "discovery":discovered,"priority":bool(discovered and priority),
     "quote_screen_pass":quote_pass,"blockers":blockers,
     "spread_pct":screen["spread_pct"],"ask_premium_vs_last_trade_pct":screen["ask_premium_vs_last_trade_pct"],
     "quote_ask":screen["quote_ask"],"trade_age_seconds":screen["trade_age_seconds"],
     "quote_age_seconds":screen["quote_age_seconds"],
     "buy_approved":False,"order_allowed":False,
     "caveat":"ENTRY_READY_SHADOW is a quote screen, not expected profit or fill. No NBBO, fees, halt or out-of-sample edge. Frozen BUY remains disabled."}
