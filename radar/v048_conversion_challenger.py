"""SAG-30 v0.4.8 future-only conversion challenger. SHADOW / NOT BUY."""
import argparse,json,sqlite3,statistics
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo("America/New_York"); VER="SAG-30-v0.4.8-CONVERSION-CHALLENGER-PROSPECTIVE-SHADOW"
LO,HI,ACT,SPR=1.5,8.0,2.0,2.0; MINM,MAXM,ADV,STEPS,VRET,GB=2,10,2.0,2,0.50,0.40
def D(s): return datetime.fromisoformat(str(s).replace("Z","+00:00"))
def init(db):
 db.executescript("""CREATE TABLE IF NOT EXISTS v048_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS v048_state(session TEXT,symbol TEXT,source_signal_ts TEXT,source_signal_source_ts TEXT,entry_change REAL,activity_ratio REAL,signal_spread_pct REAL,signal_bar_volume REAL,signal_bar_high_pct REAL,status TEXT,stage2_ts TEXT,stage2_change REAL,max_change REAL,positive_steps INTEGER,volume_retention REAL,giveback_fraction REAL,last_eval_ts TEXT,PRIMARY KEY(session,symbol,source_signal_ts));""")
 r=db.execute("SELECT value FROM v048_meta WHERE key='activated_at'").fetchone()
 if r:return r[0]
 x=datetime.now(timezone.utc).isoformat();db.execute("INSERT INTO v048_meta VALUES('activated_at',?)",(x,));db.execute("INSERT INTO v048_meta VALUES('version',?)",(VER,));db.commit();return x
def seed(db,sess,act):
 rows=db.execute("""SELECT symbol,first_signal_ts,first_signal_source_ts,first_signal_change,flow_activity_ratio,signal_bid,signal_ask,signal_spread_pct,signal_minute_bar_present FROM fast_path_v047_state WHERE session=? AND first_signal_type='FILTERED_FLOW' AND first_signal_ts>=?""",(sess,act)).fetchall();n=0
 for s,st,src,p,a,bid,ask,sp,mb in rows:
  if None in (p,a,bid,ask,sp) or not(LO<=p<=HI and a>=ACT and sp<=SPR and int(mb or 0)==1):continue
  o=db.execute("SELECT bar_volume,bar_high_pct FROM fast_path_v047_observations WHERE session=? AND symbol=? AND source_ts=? LIMIT 1",(sess,s,src)).fetchone()
  vol=float(o[0]) if o and o[0] is not None else None; high=float(o[1]) if o and o[1] is not None else float(p); now=datetime.now(timezone.utc).isoformat()
  c=db.execute("""INSERT OR IGNORE INTO v048_state VALUES(?,?,?,?,?,?,?,?,?,'STAGE1_WATCH',NULL,NULL,?,0,NULL,NULL,?)""",(sess,s,st,src,float(p),float(a),float(sp),vol,high,float(p),now));n+=int(c.rowcount or 0)
 return n
def evaluate(db,sess):
 now=datetime.now(timezone.utc);yes=no=0
 for s,st,src,entry,svol,shigh in db.execute("SELECT symbol,source_signal_ts,source_signal_source_ts,entry_change,signal_bar_volume,signal_bar_high_pct FROM v048_state WHERE session=? AND status='STAGE1_WATCH'",(sess,)).fetchall():
  age=(now-D(src)).total_seconds()/60
  rr=db.execute("SELECT source_ts,change_pct,bar_high_pct,bar_volume FROM fast_path_v047_observations WHERE session=? AND symbol=? AND minute_bar_present=1 AND source_ts>? ORDER BY source_ts",(sess,s,src)).fetchall()
  f=[((D(x[0])-D(src)).total_seconds()/60,float(x[1]),float(x[2] if x[2] is not None else x[1]),float(x[3] or 0)) for x in rr]; f=[x for x in f if 0<x[0]<=MAXM]
  if f:
   ch=[x[1] for x in f];hh=[x[2] for x in f];vv=[x[3] for x in f if x[3]>0];mx=max([entry]+ch);pos=0;prev=entry
   for x in ch:
    if x>prev:pos+=1
    prev=x
   vr=statistics.median(vv)/svol if svol and vv else None;adv=mx-entry;latest=ch[-1];gb=(mx-latest)/adv if adv>0 else 1.0
   ok=max(x[0] for x in f)>=MINM and max(hh)>shigh and adv>=ADV and pos>=STEPS and vr is not None and vr>=VRET and gb<=GB
   if ok:
    db.execute("UPDATE v048_state SET status='STAGE2_CONVERSION_SHADOW',stage2_ts=?,stage2_change=?,max_change=?,positive_steps=?,volume_retention=?,giveback_fraction=?,last_eval_ts=? WHERE session=? AND symbol=? AND source_signal_ts=?",(now.isoformat(),latest,mx,pos,vr,gb,now.isoformat(),sess,s,st));yes+=1;continue
   db.execute("UPDATE v048_state SET max_change=?,positive_steps=?,volume_retention=?,giveback_fraction=?,last_eval_ts=? WHERE session=? AND symbol=? AND source_signal_ts=?",(mx,pos,vr,gb,now.isoformat(),sess,s,st))
  if age>MAXM:
   db.execute("UPDATE v048_state SET status='EXPIRED_NO_CONVERSION',last_eval_ts=? WHERE session=? AND symbol=? AND source_signal_ts=? AND status='STAGE1_WATCH'",(now.isoformat(),sess,s,st));no+=1
 return yes,no
def report(db,sess,act,out):
 rows=db.execute("SELECT symbol,source_signal_ts,entry_change,activity_ratio,signal_spread_pct,status,stage2_ts,stage2_change,max_change,positive_steps,volume_retention,giveback_fraction FROM v048_state WHERE session=? ORDER BY source_signal_ts",(sess,)).fetchall()
 keys=["symbol","source_signal_ts","entry_change_pct","activity_ratio","signal_spread_pct","status","stage2_ts","stage2_change_pct","max_change_pct","positive_steps","volume_retention","giveback_fraction"];items=[dict(zip(keys,r)) for r in rows];counts={}
 for x in items:counts[x["status"]]=counts.get(x["status"],0)+1
 p={"status":VER,"authoritative":False,"buy":False,"activated_at":act,"session":sess,"generated_at":datetime.now(timezone.utc).isoformat(),"preregistered_gates":{"entry_change_pct":[LO,HI],"min_activity_ratio":ACT,"max_spread_pct":SPR,"confirmation_window_minutes":[MINM,MAXM],"min_advance_pp":ADV,"min_positive_steps":STEPS,"min_volume_retention":VRET,"max_giveback_fraction":GB},"counts":counts,"signals":items,"note":"Future-only; pre-activation signals receive zero credit. v0.3.3/v0.4.7 unchanged. Never BUY."}
 Path(out).write_text(json.dumps(p,indent=2,sort_keys=True)+"\n");return p
def main():
 a=argparse.ArgumentParser();a.add_argument("--db",default="state/radar.sqlite3");a.add_argument("--out",default="state/v048_conversion_challenger_report.json");x=a.parse_args();db=sqlite3.connect(x.db);act=init(db);sess=datetime.now(timezone.utc).astimezone(ET).date().isoformat();n=seed(db,sess,act);y,z=evaluate(db,sess);db.commit();p=report(db,sess,act,x.out);db.commit();print(json.dumps({"activated_at":act,"new_stage1":n,"new_stage2":y,"expired":z,"counts":p["counts"]},sort_keys=True))
if __name__=="__main__":main()
