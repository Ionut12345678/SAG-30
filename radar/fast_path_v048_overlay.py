"""SAG-30 v0.4.8 prospective OOS overlay.
Reads completed FAST-PATH observations, logs EVENT + v0.4.7 FILTERED_FLOW prospectively.
Research-only. Does not modify v0.3.3, existing FAST-PATH state, or signal bridge.
"""
import argparse,json,sqlite3,statistics
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
THRESHOLD=1.50

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS fast_path_v048_observations(
      session TEXT NOT NULL,symbol TEXT NOT NULL,source_ts TEXT NOT NULL,retrieval_ts TEXT NOT NULL,
      change_pct REAL,bar_volume REAL,bid REAL,ask REAL,spread_pct REAL,
      minute_bar_present INTEGER,consecutive_minute_bar INTEGER,catalyst TEXT,
      PRIMARY KEY(session,symbol,source_ts)
    );
    CREATE TABLE IF NOT EXISTS fast_path_v048_state(
      session TEXT NOT NULL,symbol TEXT NOT NULL,first_seen_ts TEXT NOT NULL,last_seen_ts TEXT NOT NULL,
      base_flow_decided INTEGER NOT NULL DEFAULT 0,
      event_seen INTEGER NOT NULL DEFAULT 0,event_first_ts TEXT,event_first_change REAL,
      filtered_flow_seen INTEGER NOT NULL DEFAULT 0,flow_first_ts TEXT,flow_first_change REAL,flow_activity_ratio REAL,
      first_signal_ts TEXT,first_signal_type TEXT,first_signal_change REAL,
      PRIMARY KEY(session,symbol)
    );
    """)

def prior_volume_ratio(db,session,symbol,current_volume):
    rows=db.execute(
      "SELECT bar_volume FROM fast_path_v048_observations WHERE session=? AND symbol=? "
      "AND minute_bar_present=1 AND bar_volume>0 ORDER BY source_ts DESC LIMIT 20",(session,symbol)
    ).fetchall()
    vals=[float(r[0]) for r in rows if r[0] is not None and float(r[0])>0]
    if not vals:return None
    base=statistics.median(vals)
    return current_volume/base if base>0 else None

def upsert_state(db,session,symbol,now):
    row=db.execute("SELECT * FROM fast_path_v048_state WHERE session=? AND symbol=?",(session,symbol)).fetchone()
    if row:return
    db.execute("INSERT INTO fast_path_v048_state(session,symbol,first_seen_ts,last_seen_ts) VALUES(?,?,?,?)",
      (session,symbol,now,now))

def process(db,session):
    # Latest FAST-PATH event per symbol from the most recent loop. Only rows not yet
    # represented by their source timestamp can enter prospective v0.4.8 history.
    latest=db.execute("""
      SELECT e.symbol,e.retrieval_ts,e.change_pct,e.bid,e.ask,e.spread_pct,
             e.minute_bar_present,e.consecutive_minute_bar,e.catalyst,
             s.last_source_ts,s.last_volume,s.positive_flow_count,s.peak_change_pct,s.last_state
      FROM fast_path_events e
      JOIN fast_path_state s ON s.session=e.session AND s.symbol=e.symbol
      JOIN (SELECT symbol,MAX(id) id FROM fast_path_events WHERE session=? GROUP BY symbol) z ON z.id=e.id
      WHERE e.session=?
    """,(session,session)).fetchall()
    new_obs=event_new=flow_pass=flow_reject=0
    for r in latest:
        symbol,retrieval,pct,bid,ask,spread,mb,consec,catalyst,source_ts,vol,pos_count,peak,state=r
        if not source_ts:continue
        exists=db.execute("SELECT 1 FROM fast_path_v048_observations WHERE session=? AND symbol=? AND source_ts=?",
          (session,symbol,source_ts)).fetchone()
        if exists:continue
        now=retrieval or datetime.now(timezone.utc).isoformat();upsert_state(db,session,symbol,now)
        st=db.execute(
          "SELECT base_flow_decided,event_seen,filtered_flow_seen,first_signal_ts FROM fast_path_v048_state WHERE session=? AND symbol=?",
          (session,symbol)).fetchone()
        base_decided,event_seen,filtered_seen,first_signal=map(lambda x:x,st)
        prior_peak=float(peak if peak is not None else pct or 0)
        early=prior_peak<10 and pct is not None and float(pct)<10
        ratio=prior_volume_ratio(db,session,symbol,float(vol or 0)) if mb and vol and float(vol)>0 else None

        event_candidate=bool(catalyst) and early and not event_seen
        base_flow_candidate=(not base_decided and early and pct is not None and 0<float(pct)<10 and int(pos_count or 0)>=2)
        filtered_candidate=bool(base_flow_candidate and ratio is not None and ratio>=THRESHOLD)

        db.execute("""INSERT INTO fast_path_v048_observations
          (session,symbol,source_ts,retrieval_ts,change_pct,bar_volume,bid,ask,spread_pct,minute_bar_present,consecutive_minute_bar,catalyst)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (session,symbol,source_ts,now,pct,vol,bid,ask,spread,int(mb or 0),int(consec or 0),catalyst or ""))
        new_obs+=1
        sets=["last_seen_ts=?"];args=[now]
        signal_type=None
        if event_candidate:
            sets+=["event_seen=1","event_first_ts=?","event_first_change=?"];args += [now,pct];event_new+=1
            signal_type="EVENT"
        if base_flow_candidate:
            sets+=["base_flow_decided=1"]
            if filtered_candidate:
                sets+=["filtered_flow_seen=1","flow_first_ts=?","flow_first_change=?","flow_activity_ratio=?"]
                args += [now,pct,ratio];flow_pass+=1
                if signal_type is None:signal_type="FILTERED_FLOW"
            else:flow_reject+=1
        if signal_type and not first_signal:
            sets+=["first_signal_ts=?","first_signal_type=?","first_signal_change=?"];args += [now,signal_type,pct]
        args += [session,symbol]
        db.execute("UPDATE fast_path_v048_state SET "+",".join(sets)+" WHERE session=? AND symbol=?",args)
    return {"new_observations":new_obs,"new_events":event_new,"new_filtered_flows":flow_pass,"new_flow_rejects":flow_reject}

def report(db,session,out):
    counts={}
    q=db.execute("""SELECT
      COUNT(*),SUM(event_seen),SUM(filtered_flow_seen),
      SUM(CASE WHEN first_signal_ts IS NOT NULL THEN 1 ELSE 0 END),
      SUM(CASE WHEN base_flow_decided=1 AND filtered_flow_seen=0 THEN 1 ELSE 0 END)
      FROM fast_path_v048_state WHERE session=?""",(session,)).fetchone()
    counts={"symbols":int(q[0] or 0),"event_seen":int(q[1] or 0),"filtered_flow_seen":int(q[2] or 0),
      "combined_first_signals":int(q[3] or 0),"flow_activity_rejects":int(q[4] or 0)}
    rows=[]
    for r in db.execute("""SELECT symbol,event_seen,event_first_ts,event_first_change,filtered_flow_seen,
      flow_first_ts,flow_first_change,flow_activity_ratio,first_signal_ts,first_signal_type,first_signal_change,last_seen_ts
      FROM fast_path_v048_state WHERE session=? AND first_signal_ts IS NOT NULL ORDER BY first_signal_ts""",(session,)):
        rows.append({"symbol":r[0],"event_seen":bool(r[1]),"event_first_ts":r[2],"event_first_change":r[3],
          "filtered_flow_seen":bool(r[4]),"flow_first_ts":r[5],"flow_first_change":r[6],"flow_activity_ratio":r[7],
          "first_signal_ts":r[8],"first_signal_type":r[9],"first_signal_change":r[10],"last_seen_ts":r[11]})
    execq=db.execute("""SELECT COUNT(*),SUM(CASE WHEN ask IS NOT NULL THEN 1 ELSE 0 END),
      AVG(spread_pct),AVG(CASE WHEN consecutive_minute_bar=1 THEN 1.0 ELSE 0.0 END)
      FROM fast_path_v048_observations WHERE session=?""",(session,)).fetchone()
    payload={"status":"SAG-30-v0.4.8-PROSPECTIVE-OOS-SHADOW","authoritative":False,"buy":False,
      "session":session,"generated_at":datetime.now(timezone.utc).isoformat(),"activity_ratio_threshold":THRESHOLD,
      "counts":counts,"signals":rows,
      "telemetry":{"observations":int(execq[0] or 0),"ask_available_rate":((execq[1] or 0)/execq[0] if execq[0] else None),
        "avg_spread_pct":execq[2],"consecutive_1m_rate":execq[3]},
      "note":"Prospective research only. v0.3.3 FROZEN and existing bridge decisions unchanged."}
    Path(out).parent.mkdir(parents=True,exist_ok=True);Path(out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10))
    return payload

def main():
    p=argparse.ArgumentParser();p.add_argument("--db",default="state/radar.sqlite3");p.add_argument("--out",default="state/fast_path_v048_report.json");a=p.parse_args()
    db=sqlite3.connect(a.db);init(db);session=datetime.now(timezone.utc).astimezone(ET).date().isoformat()
    delta=process(db,session);db.commit();payload=report(db,session,a.out);db.commit()
    print(json.dumps({"delta":delta,"counts":payload["counts"],"telemetry":payload["telemetry"]},sort_keys=True))
if __name__=="__main__":main()
