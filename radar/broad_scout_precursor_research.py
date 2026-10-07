"""Broad scout precursor routing study. DEV descriptive / NOT BUY."""
import sqlite3,json
db=sqlite3.connect('/tmp/r.db')
# outcomes from observed FAST-PATH peaks
out={}
for se,sy,pk in db.execute("select session,symbol,max(coalesce(bar_high_pct,change_pct)) from fast_path_events group by session,symbol"):
    if pk is not None and pk>=5: out[(se,sy)]=float(pk)
specs={
 "RANK50":lambda r:(r[6] is not None and r[6]<=50) or (r[7] is not None and r[7]<=50),
 "RANK100":lambda r:(r[6] is not None and r[6]<=100) or (r[7] is not None and r[7]<=100),
 "RANK100_CHG100":lambda r:(r[5] is not None and r[5]<=100) or (r[6] is not None and r[6]<=100) or (r[7] is not None and r[7]<=100),
}
# columns session,symbol,retrieval,pct,accel,rank_change,rank_accel,rank_impulse,rank_turnover,selected,sticky
rows=db.execute("select session,symbol,retrieval_ts,change_pct,acceleration_pp_per_min,rank_change,rank_acceleration,rank_impulse,rank_turnover,selected,sticky from scout_history order by session,symbol,retrieval_ts").fetchall()
from collections import defaultdict
G=defaultdict(list)
for r in rows:G[(r[0],r[1])].append(r)
cases=[]
for k,pk in out.items():
 rr=G.get(k,[]); rec={"session":k[0],"symbol":k[1],"peak":pk,"scout_seen":bool(rr),"early_scout":False}
 for n in specs:rec[n]=False
 for r in rr:
    p=float(r[3])
    if p>=10:break
    if 0<p<10:
      rec["early_scout"]=True
      for n,fn in specs.items():
        if fn(r):rec[n]=True
 cases.append(rec)
def M(n):
 w=[x for x in cases if x["peak"]>=30];h=[x for x in cases if x["peak"]<30];ew=[x for x in w if x["early_scout"]]
 return dict(winners=len(w),hard_negatives=len(h),early_scout_winners=len(ew),winner_hits=sum(x[n] for x in w),early_winner_hits=sum(x[n] for x in ew),false_hits=sum(x[n] for x in h),
  early_recall=sum(x[n] for x in ew)/len(ew) if ew else None,fpr=sum(x[n] for x in h)/len(h) if h else None)
O={"status":"BROAD_SCOUT_PRECURSOR_DEV_NOT_OOS_NOT_BUY","metrics":{n:M(n) for n in specs},
   "winner_detail":[x for x in cases if x["peak"]>=30],
   "note":"Routing study only; no model gate changes."}
open('reports/broad_scout_precursor_dev.json','w').write(json.dumps(O,indent=2,sort_keys=True))
