"""Evaluate chronological simulated entry and future observed prices.

Strictly post-entry observations, no same-bar hindsight. Reports indicative
gross/net returns; never assumes an executable fill.
"""
import math
VERSION="SAG30_PAPER_OUTCOME_V0_3"
def _valid(x):
 return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0
def evaluate(entry_ask,entry_ts,future_observations,roundtrip_cost_pct=2.0):
 if not _valid(entry_ask):return {"version":VERSION,"status":"INVALID_ENTRY","not_buy":True}
 if not isinstance(roundtrip_cost_pct,(int,float)) or not 0<=roundtrip_cost_pct<100:
  return {"version":VERSION,"status":"INVALID_COST","not_buy":True}
 points=sorted([(r["ts"],r["price"]) for r in future_observations
                if isinstance(r,dict) and isinstance(r.get("ts"),str) and
                r["ts"]>entry_ts and _valid(r.get("price"))])
 if not points:return {"version":VERSION,"status":"CENSORED_NO_FUTURE_PRINTS","not_buy":True}
 high=max(p for _,p in points)
 last=points[-1][1]
 gross_high=100*(high/entry_ask-1)
 gross_last=100*(last/entry_ask-1)
 return {"version":VERSION,"status":"INDICATIVE_OUTCOME_NOT_FILL","not_buy":True,
  "entry_ask":entry_ask,"entry_ts":entry_ts,"future_observations":len(points),
  "max_future_observed_price":high,"last_future_observed_price":last,
  "gross_max_pct":round(gross_high,3),"net_max_after_assumed_cost_pct":round(gross_high-roundtrip_cost_pct,3),
  "gross_last_pct":round(gross_last,3),"net_last_after_assumed_cost_pct":round(gross_last-roundtrip_cost_pct,3),
  "assumed_roundtrip_cost_pct":roundtrip_cost_pct,
  "caveat":"Last-trade observations are not bid-side exit fills; high is hindsight maximum, not a realizable strategy exit."}
