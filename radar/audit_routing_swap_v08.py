"""SAG30 v0.8 routing counterfactual. Research only; no BUY."""
import sqlite3,json,argparse
from collections import defaultdict,Counter
from pathlib import Path
def audit(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 runs=defaultdict(list);symbols=defaultdict(list)
 for r in db.execute("SELECT session,run_id,symbol,retrieval_ts,change_pct,rank_change,rank_turnover,selected FROM scout_history ORDER BY session,run_id,rank_change,symbol"):
  runs[(r["session"],r["run_id"])].append(r);symbols[(r["session"],r["symbol"])].append(r)
 def outcome(r):
  future=[x["change_pct"] for x in symbols[(r["session"],r["symbol"])] if x["retrieval_ts"]>r["retrieval_ts"] and x["change_pct"] is not None]
  return None if not future else (any(x>=30 for x in future),any(x>=50 for x in future))
 seen=set();stats={k:Counter() for k in (0,5,10,20)};examples=[]
 for (session,run_id),rows in sorted(runs.items()):
  first=[]
  for r in rows:
   key=(session,r["symbol"])
   if r["change_pct"] is None or not 0<=r["change_pct"]<10 or key in seen:continue
   seen.add(key)
   if r["rank_change"] is not None and r["rank_change"]<=100:first.append(r)
  if not first:continue
  selected=[r for r in rows if r["selected"]]
  selected_symbols={r["symbol"] for r in selected}
  protected={r["symbol"] for r in first if r["symbol"] in selected_symbols}
  missing=sorted((r for r in first if r["symbol"] not in selected_symbols),key=lambda r:(r["rank_change"],r["symbol"]))
  removable=sorted((r for r in selected if r["symbol"] not in protected),key=lambda r:(r["rank_change"] if r["rank_change"] is not None else 10**9,r["symbol"]),reverse=True)
  for k,m in stats.items():
   n=min(k,len(missing),len(removable));m["runs"]+=1;m["baseline_selected"]+=len(protected)
   m["added"]+=n;m["displaced"]+=n;m["unselected"]+=len(missing)-n
   for prefix,items in (("added",missing[:n]),("displaced",removable[:n])):
    for r in items:
     result=outcome(r)
     if result is None:m[prefix+"_censored"]+=1
     else:
      m[prefix+"_labeled"]+=1
      m[prefix+"_later30"]+=int(result[0]);m[prefix+"_later50"]+=int(result[1])
   if k and n and len(examples)<20:
    examples.append({"session":session,"run_id":run_id,"slots":k,"added":[r["symbol"] for r in missing[:n]],"displaced":[r["symbol"] for r in removable[:n]]})
 variants={}
 for k,m in stats.items():
  variants[str(k)]={**dict(m),"net_later30":m["added_later30"]-m["displaced_later30"],"net_later50":m["added_later50"]-m["displaced_later50"]}
 return {"version":"SAG30_ROUTING_SWAP_V08","status":"HISTORICAL_SHADOW_NOT_BUY","variants":variants,"examples":examples,"limitations":"First early observation, later SCOUT price threshold vs previous close, incomplete/censored labels; displaced candidates may already exceed 10%. No actual deep fetch or fill; not an executable edge."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True)
 print(json.dumps(audit(p.parse_args().db),sort_keys=True))
