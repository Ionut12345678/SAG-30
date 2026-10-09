"""Forward sampled-price comparison: PAPER and matched controls, same feed and clock.

Research-only, never a BUY. No price interpolation or treating missing data as loss.
"""
import argparse,json,sqlite3
from datetime import datetime
from radar.early_paper_momentum_shadow_v14 import build as preentry
def stamp(value):
 try:return datetime.fromisoformat(value.replace("Z","+00:00"))
 except (ValueError,TypeError,AttributeError):return None
def build(path):
 base=preentry(path)
 if base.get("status")!="EXPLORATORY_NOT_BUY":return {"status":"MISSING_INPUT"}
 db=sqlite3.connect(path);db.row_factory=sqlite3.Row
 def forward(symbol,run,minutes):
  anchor=db.execute("SELECT retrieval_ts,change_pct FROM scout_history WHERE run_id=? AND symbol=?",(run,symbol)).fetchone()
  if not anchor or stamp(anchor["retrieval_ts"]) is None:return {"status":"NO_ENTRY_SCOUT"}
  start=stamp(anchor["retrieval_ts"]);p=float(anchor["change_pct"])
  if p<=-100:return {"status":"INVALID_BASELINE"}
  rows=db.execute("""SELECT retrieval_ts,change_pct FROM scout_history
   WHERE symbol=? AND run_id>? AND session=(SELECT session FROM scout_history WHERE symbol=? AND run_id=?)
   ORDER BY run_id""",(symbol,run,symbol,run)).fetchall()
  vals=[]
  for row in rows:
   t=stamp(row["retrieval_ts"])
   if t is None:continue
   elapsed=(t-start).total_seconds()/60
   if 0<elapsed<=minutes:
    vals.append(100*((100+float(row["change_pct"]))/(100+p)-1))
  if not vals:return {"status":"NO_FUTURE_SAMPLE","observations":0}
  return {"status":"PARTIAL_SAMPLED","observations":len(vals),
   "max_sampled_return_pct":round(max(vals),4),
   "last_sampled_return_pct":round(vals[-1],4),
   "sampled_hit10":max(vals)>=10,"sampled_hit30":max(vals)>=30,
   "sampled_hit50":max(vals)>=50}
 def decorate(items,minutes):
  return [{**r,"forward":forward(r["symbol"],r["entry_run_id"],minutes)} for r in items]
 def summarize(rows):
  valid=[r for r in rows if r["forward"]["status"]=="PARTIAL_SAMPLED"]
  return {"total":len(rows),"with_future_samples":len(valid),
   "observed_hit10":sum(r["forward"]["sampled_hit10"] for r in valid),
   "observed_hit30":sum(r["forward"]["sampled_hit30"] for r in valid),
   "observed_hit50":sum(r["forward"]["sampled_hit50"] for r in valid)}
 windows={}
 for minutes in (60,240):
  paper=decorate(base["paper_cases"],minutes)
  controls=decorate(base["control_cases"],minutes)
  pairs=[]
  for p in paper:
   matching=[c for c in controls if c["entry_symbol"]==p["symbol"] and c["entry_run_id"]==p["entry_run_id"]]
   if p["forward"]["status"]!="PARTIAL_SAMPLED":continue
   usable=[c for c in matching if c["forward"]["status"]=="PARTIAL_SAMPLED"]
   if not usable:continue
   pairs.append({"symbol":p["symbol"],"control_count":len(usable),
    "paper_max_pct":p["forward"]["max_sampled_return_pct"],
    "control_mean_max_pct":round(sum(c["forward"]["max_sampled_return_pct"] for c in usable)/len(usable),4),
    "paper_hit30":p["forward"]["sampled_hit30"],
    "control_hit30_count":sum(c["forward"]["sampled_hit30"] for c in usable)})
  windows[str(minutes)+"m"]={"paper":summarize(paper),"controls":summarize(controls),
   "paired_with_both_observed":len(pairs),"pairs":pairs}
 return {"version":"SAG30_PAPER_MATCHED_OUTCOME_V15","status":"PARTIAL_PROSPECTIVE_SHADOW_NOT_BUY",
  "windows":windows,
  "method":"Same-run scout change_pct baseline, future scout change_pct samples only, 60m and 240m from initial scout snapshot. Controls fixed pre-outcome by v1.4.",
  "limitations":["Scout sample changes are not executable returns, intrabar highs, or IEX entry ask",
  "Only rows with future samples counted; censored rows are NOT losses",
  "Missing feed coverage may bias comparisons; controls are not known losers",
  "Some controls may repeat across pairs; no independence or significance claim",
  "Frozen production BUY rules untouched"]}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--out",required=True)
 a=p.parse_args()
 with open(a.out,"w") as f:json.dump(build(a.db),f,indent=2)
