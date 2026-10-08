"""SAG-30 BUY Candidate v0.1: immutable, research-only state machine.

A quote-screen pass permits a PAPER REVIEW, never a live order. Time-to-live
and source timestamps are checked before advancing any state.
"""
from datetime import datetime,timezone
from radar.buy_triage_shadow import triage

VERSION="SAG30_BUY_CANDIDATE_V0_1_SHADOW"
def _time(ts):
 try:
  d=datetime.fromisoformat(ts.replace("Z","+00:00"))
  return d.astimezone(timezone.utc) if d.tzinfo else None
 except (ValueError,TypeError,AttributeError):return None

def decide(snapshot,retrieval_ts,quality,change_pct,state,discovery,priority,
           observations=1,first_seen_ts=None):
 r=triage(snapshot,retrieval_ts,quality,change_pct,state,discovery,priority,observations)
 now=_time(retrieval_ts);first=_time(first_seen_ts or retrieval_ts)
 age=(now-first).total_seconds() if now and first else None
 reasons=list(r["blockers"])
 if age is None or age<0:reasons.append("INVALID_FIRST_SEEN")
 elif age>900:reasons.append("SIGNAL_TTL_EXPIRED")
 if not isinstance(change_pct,(int,float)) or isinstance(change_pct,bool) or not 0<=change_pct<10:
  reasons.append("NOT_EARLY_ENTRY_UNDER_10")
 if r["route"]=="PAPER_ENTRY_REVIEW" and not reasons:
  stage="PAPER_REVIEW_ONLY"
 elif r["route"]=="RECHECK_FAST" and "SIGNAL_TTL_EXPIRED" not in reasons:
  stage="FAST_RECHECK"
 elif r["route"]=="WATCH_DISCOVERY" and "SIGNAL_TTL_EXPIRED" not in reasons:
  stage="WATCH"
 else:stage="REJECT_OR_EXPIRED"
 return {"version":VERSION,"stage":stage,"reasons":reasons,
         "first_seen_age_seconds":age,"recheck_seconds":r["recheck_seconds"] if stage in ("FAST_RECHECK","WATCH") else None,
         "paper_review":stage=="PAPER_REVIEW_ONLY",
         "live_buy":False,"order_allowed":False,
         "validation_status":"UNVALIDATED_NO_EXECUTION_EVIDENCE",
         "policy":"No real BUY until independent prospective evidence and realistic NBBO/fill/cost evaluation."}
