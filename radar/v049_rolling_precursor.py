"""SAG-30 v0.4.9 rolling precursor challenger. Prospective SHADOW / NOT BUY.
Routing is supplied by broad scout; this layer uses deduplicated v0.4.7 minute observations
but does NOT change v0.4.7 or v0.4.8 semantics.
"""
import argparse,json,sqlite3,statistics
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo("America/New_York")
VER="SAG-30-v0.4.9-ROLLING-PRECURSOR-PROSPECTIVE-SHADOW"
LO,HI,ACT,SPR=1.0,8.0,1.5,2.0
MAX_GAP=5.0
def D(s): return datetime.fromisoformat(str(s).replace("Z","+00:00"))
def init(db):
 db.executescript("""CREATE TABLE IF NOT EXISTS v049_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS v049_state(session TEXT,symbol TEXT,first_watch_ts TEXT,source_ts TEXT,entry_change REAL,activity_ratio REAL,spread_pct REAL,status TEXT,last_eval_ts TEXT,PRIMARY KEY(session,symbol));""")
 r=db.execute("select value from v049_meta where key='activated_at'").fetchone()
 if r:return r[0]
 x=datetime.now(timezone.utc).isoformat()
 db.execute("insert into v049_meta values('activated_at',?)",(x,))
 db.execute("insert into v049_meta values('version',?)",(VER,))
 db.commit();return x
def find_watch(db,sess,sym,act):
 rr=db.execute("""select source_ts,retrieval_ts,change_pct,bar_high_pct,bar_volume,bid,ask,spread_pct,minute_bar_present
   from fast_path_v047_observations where session=? and symbol=? and retrieval_ts>=? order by source_ts""",(sess,sym,act)).fetchall()
 vols=[];streak=0;prev=None;prevts=None
 for src,ret,p,h,v,bid,ask,sp,mb in rr:
  if p is None:continue
  p=float(p);h=float(h if h is not None else p)
  if h>=10:break
  if not int(mb or 0) or v is None or float(v)<=0:continue
  med=statistics.median(vols[-20:]) if vols else 0
  ratio=float(v)/med if med>0 else None
  positive=False
  if prev is not None and prevts is not None:
   dt=(D(src)-D(prevts)).total_seconds()/60
   positive=bool(0<dt<=MAX_GAP and p>prev)
  streak=streak+1 if positive else 0
  execok=bid is not None and ask is not None and sp is not None and float(sp)<=SPR
  if LO<=p<=HI and streak>=2 and ratio is not None and ratio>=ACT and execok:
   return dict(source_ts=src,retrieval_ts=ret,entry=p,activity=ratio,spread=float(sp))
  vols.append(float(v));prev=p;prevts=src
 return None
def process(db,sess,act):
 syms=[r[0] for r in db.execute("select distinct symbol from fast_path_v047_observations where session=? and retrieval_ts>=?",(sess,act))]
 new=0
 for s in syms:
  if db.execute("select 1 from v049_state where session=? and symbol=?",(sess,s)).fetchone():continue
  w=find_watch(db,sess,s,act)
  if not w:continue
  now=datetime.now(timezone.utc).isoformat()
  db.execute("insert into v049_state values(?,?,?,?,?,?,?,'ROLLING_PRECURSOR_WATCH',?)",
    (sess,s,w["retrieval_ts"],w["source_ts"],w["entry"],w["activity"],w["spread"],now));new+=1
 return new
def report(db,sess,act,out):
 rows=db.execute("select symbol,first_watch_ts,source_ts,entry_change,activity_ratio,spread_pct,status,last_eval_ts from v049_state where session=? order by first_watch_ts",(sess,)).fetchall()
 keys=["symbol","first_watch_ts","source_ts","entry_change_pct","activity_ratio","spread_pct","status","last_eval_ts"]
 items=[dict(zip(keys,r)) for r in rows]
 p={"status":VER,"authoritative":False,"buy":False,"activated_at":act,"session":sess,
 "generated_at":datetime.now(timezone.utc).isoformat(),"counts":{"rolling_precursor_watch":len(items)},
 "gates":{"entry_change_pct":[LO,HI],"min_activity_ratio":ACT,"max_spread_pct":SPR,"positive_steps":2,"max_step_gap_minutes":MAX_GAP},
 "signals":items,"note":"Future-only rolling precursor WATCH. Broad scout is routing only. No changes to v0.3.3/v0.4.7/v0.4.8. Never BUY."}
 Path(out).write_text(json.dumps(p,indent=2,sort_keys=True)+"\n");return p
def main():
 a=argparse.ArgumentParser();a.add_argument("--db",default="state/radar.sqlite3");a.add_argument("--out",default="state/v049_rolling_precursor_report.json");x=a.parse_args()
 db=sqlite3.connect(x.db);act=init(db);sess=datetime.now(timezone.utc).astimezone(ET).date().isoformat();n=process(db,sess,act);db.commit();p=report(db,sess,act,x.out);db.commit()
 print(json.dumps({"activated_at":act,"new_watches":n,"count":p["counts"]["rolling_precursor_watch"]},sort_keys=True))
if __name__=="__main__":main()
