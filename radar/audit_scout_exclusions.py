"""Diagnose observed SCOUT rows excluded from multi-engine; no outcomes or BUY."""
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path
def analyze(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True)
 db.row_factory=sqlite3.Row
 rows=db.execute("""SELECT s.run_id,s.session,s.symbol,s.change_pct,s.rank_change,
 s.rank_acceleration,s.rank_impulse,s.rank_turnover,s.selected,
 CASE WHEN m.symbol IS NULL THEN 0 ELSE 1 END AS covered
 FROM scout_history s LEFT JOIN multi_engine_scores m
 ON s.run_id=m.run_id AND s.symbol=m.symbol""").fetchall()
 buckets=Counter(); selected=Counter(); sessions=Counter()
 for r in rows:
  p=r["change_pct"]
  b= "below_minus_10" if p < -10 else "minus_10_to_0" if p < 0 else "zero_to_5" if p < 5 else "five_to_10" if p < 10 else "ten_to_20" if p < 20 else "above_20"
  k="covered" if r["covered"] else "excluded"
  buckets[(k,b)]+=1
  selected[k]+=int(r["selected"])
  sessions[(k,r["session"])]+=1
 return {"total_rows":len(rows),"excluded_rows":sum(v for (k,b),v in buckets.items() if k=="excluded"),
 "by_change_pct":{k:{b:v for (lane,b),v in buckets.items() if lane==k} for k in ("covered","excluded")},
 "selected_by_lane":dict(selected),"sessions":{k:{s:v for (lane,s),v in sessions.items() if lane==k} for k in ("covered","excluded")},
 "status":"DESCRIPTIVE_ONLY_NO_FORWARD_OUTCOMES_NOT_BUY"}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);a=p.parse_args()
 print(json.dumps(analyze(a.db),sort_keys=True))
