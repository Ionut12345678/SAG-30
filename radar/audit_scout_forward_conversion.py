"""Forward-only SCOUT exclusion conversion study; observed prices vs prior close.

No executable entry returns. One first eligible observation per session-symbol,
then only strictly later SCOUT observations in that session. No BUY.
"""
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path

def analyze(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 rows=db.execute("""SELECT s.session,s.symbol,s.run_id,s.retrieval_ts,s.change_pct,
 CASE WHEN m.symbol IS NULL THEN 0 ELSE 1 END AS covered
 FROM scout_history s LEFT JOIN multi_engine_scores m
 ON m.run_id=s.run_id AND m.symbol=s.symbol
 ORDER BY s.session,s.symbol,s.retrieval_ts,s.run_id""").fetchall()
 groups={}
 for r in rows: groups.setdefault((r["session"],r["symbol"]),[]).append(r)
 result=Counter();examples=[]
 for (session,symbol),group in groups.items():
  first=next((i for i,r in enumerate(group) if 0<=r["change_pct"]<10),None)
  if first is None:continue
  entry=group[first]
  lane="covered" if entry["covered"] else "excluded"
  later=[r for r in group[first+1:] if r["retrieval_ts"]>entry["retrieval_ts"]]
  if not later:
   result[(lane,"no_followup")]+=1
   continue
  result[(lane,"followed")]+=1
  for threshold in (30,50):
   if any(r["change_pct"]>=threshold for r in later):
    result[(lane,f"observed_later_{threshold}")]+=1
    if lane=="excluded" and len(examples)<20:
     examples.append({"session":session,"symbol":symbol,"first_ts":entry["retrieval_ts"],
                      "first_change_pct":entry["change_pct"],"threshold":threshold})
 return {"status":"SHADOW_OBSERVED_ONLY","first_eligible_sessions":{
  lane:{key:result[(lane,key)] for key in ("followed","no_followup","observed_later_30","observed_later_50")}
  for lane in ("covered","excluded")},"excluded_examples":examples,
 "caveat":"First observed 0..10% SCOUT snapshot per symbol-session; later observed +30/+50% vs prior close, not entry profit. Unequal follow-up and missing bars can bias outcomes. No BUY."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);args=p.parse_args()
 print(json.dumps(analyze(args.db),sort_keys=True))
