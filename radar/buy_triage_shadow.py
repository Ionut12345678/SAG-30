"""Deterministic shadow triage for previously discovered candidates.

The research policy never approves an order. Recheck prioritization is not
a buy recommendation and does not override FROZEN gates.
"""
from radar.buy_readiness_shadow import evaluate as quote_evaluate

VERSION="BUY_TRIAGE_SHADOW_V1"
def triage(snapshot,retrieval_ts,quality,change_pct,state,discovery,priority,observations=1):
    result=quote_evaluate(snapshot,retrieval_ts,quality,change_pct,state,discovery,priority)
    blockers=result["blockers"]
    if not discovery:
        route="IGNORE"
    elif result["quote_screen_pass"]:
        route="PAPER_ENTRY_REVIEW"
    elif priority:
        route="RECHECK_FAST"
    else:
        route="WATCH_DISCOVERY"
    result.update({"triage_version":VERSION,"route":route,
        "recheck_seconds":60 if route=="RECHECK_FAST" else 300 if route=="WATCH_DISCOVERY" else None,
        "observations":max(0,int(observations)),
        "paper_entry_allowed":route=="PAPER_ENTRY_REVIEW",
        "live_buy_allowed":False,
        "missing_evidence":["CONSOLIDATED_NBBO","HALT_STATUS","FEES_AND_SLIPPAGE",
                            "INDEPENDENT_FORWARD_EDGE"],
        "note":"Paper-entry review is NOT a paper fill and is never an executable BUY."})
    return result
