"""SAG-30 v0.2: early PAPER entry screen, independent of FROZEN HOT.

No orders, no inferred quotes, no future data. Extended-hours research is
explicitly distinguished from regular-session quote actionability.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from radar.buy_actionability_shadow import _age,_positive

ET=ZoneInfo("America/New_York")
VERSION="SAG30_EARLY_PAPER_V0_2"
def evaluate(snapshot,retrieval_ts,quality,change_pct,discovery,priority,first_seen_ts=None):
 blockers=[]
 if not discovery:blockers.append("NOT_DISCOVERED")
 if quality!="OK":blockers.append("DATA_QUALITY")
 if not isinstance(change_pct,(int,float)) or isinstance(change_pct,bool) or not 0<=change_pct<10:
  blockers.append("NOT_EARLY_UNDER_10")
 try:
  now=datetime.fromisoformat(retrieval_ts.replace("Z","+00:00"))
  first=datetime.fromisoformat((first_seen_ts or retrieval_ts).replace("Z","+00:00"))
  if now.tzinfo is None or first.tzinfo is None:raise ValueError("naive")
  age=(now-first).total_seconds()
  if age<0 or age>900: blockers.append("EXPIRED_OR_FUTURE_FIRST_SEEN")
  et=now.astimezone(ET)
  minute=et.hour*60+et.minute
  if et.weekday()>=5 or not 240<=minute<1200: blockers.append("OUTSIDE_SUPPORTED_SESSION")
  session="REGULAR" if 570<=minute<960 else "EXTENDED"
 except (TypeError,ValueError,AttributeError):
  blockers.append("INVALID_TIMESTAMPS");session="UNKNOWN";age=None
 trade=(snapshot or {}).get("latestTrade") or {}
 quote=(snapshot or {}).get("latestQuote") or {}
 tp,bid,ask=trade.get("p"),quote.get("bp"),quote.get("ap")
 ta=_age(retrieval_ts,trade.get("t"));qa=_age(retrieval_ts,quote.get("t"))
 if not _positive(tp) or ta is None or not 0<=ta<=60:blockers.append("MISSING_STALE_TRADE")
 if not (_positive(bid) and _positive(ask) and ask>=bid):blockers.append("INVALID_BID_ASK")
 if qa is None or not 0<=qa<=60:blockers.append("MISSING_STALE_QUOTE")
 if not (_positive(quote.get("bs")) and _positive(quote.get("as"))):blockers.append("MISSING_QUOTE_SIZE")
 spread=100*(ask-bid)/((ask+bid)/2) if _positive(bid) and _positive(ask) and ask>=bid else None
 premium=100*(ask/tp-1) if _positive(ask) and _positive(tp) else None
 if spread is not None and spread>2:blockers.append("SPREAD_OVER_2_PCT")
 if premium is not None and premium>3:blockers.append("ASK_PREMIUM_OVER_3_PCT")
 stage="EARLY_PAPER_ENTRY_REVIEW" if not blockers else "RECHECK_FAST" if discovery and priority and "EXPIRED_OR_FUTURE_FIRST_SEEN" not in blockers else "WATCH_OR_REJECT"
 return {"version":VERSION,"stage":stage,"session":session,"blockers":blockers,
 "paper_review":stage=="EARLY_PAPER_ENTRY_REVIEW","live_buy":False,"order_allowed":False,
 "indicative_ask":ask if stage=="EARLY_PAPER_ENTRY_REVIEW" else None,
 "spread_pct":round(spread,4) if spread is not None else None,
 "premium_pct":round(premium,4) if premium is not None else None,
 "first_seen_age_seconds":age,"recheck_seconds":60 if stage=="RECHECK_FAST" else None,
 "caveat":"IEX quote is not NBBO; extended-hours quotes may be non-executable. No proven fill, edge, halt checks or costs. Research only."}
