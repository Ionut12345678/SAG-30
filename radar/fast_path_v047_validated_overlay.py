"""SAG-30 v0.4.7 VALIDATED prospective OOS overlay.
Exact historical candidate semantics, research-only. Never modifies v0.3.3 or bridge decisions.
"""
import argparse,json,sqlite3,statistics
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
THRESHOLD=1.50

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS fast_path_v047_observations(
      session TEXT NOT NULL,symbol TEXT NOT NULL,source_ts TEXT NOT NULL,retrieval_ts TEXT NOT NULL,
      change_pct REAL,bar_high_pct REAL,bar_volume REAL,bid REAL,ask REAL,spread_pct REAL,
      minute_bar_present INTEGER,catalyst TEXT,
      PRIMARY KEY(session,symbol,source_ts)
    );
    CREATE TABLE IF NOT EXISTS fast_path_v047_state(
      session TEXT NOT NULL,symbol TEXT NOT NULL,first_seen_ts TEXT NOT NULL,last_seen_ts TEXT NOT NULL,
      flow_positive_count INTEGER NOT NULL DEFAULT 0,max_high_pct REAL,
      base_flow_decided INTEGER NOT NULL DEFAULT 0,
      event_seen INTEGER NOT NULL DEFAULT 0,event_first_ts TEXT,event_first_change REAL,
      filtered_flow_seen INTEGER NOT NULL DEFAULT 0,flow_first_ts TEXT,flow_first_change REAL,flow_activity_ratio REAL,
      first_signal_ts TEXT,first_signal_source_ts TEXT,first_signal_type TEXT,first_signal_change REAL,
      signal_bid REAL,signal_ask REAL,signal_spread_pct REAL,signal_minute_bar_present INTEGER,
      PRIMARY KEY(session,symbol)
    );
    """)

def prior_volume_ratio(db,session,symbol,current_volume):
    rows=db.execute(
      "SELECT bar_volume FROM fast_path_v047_observations WHERE session=? AND symbol=? "
      "AND minute_bar_present=1 AND bar_volume>0 ORDER BY source_ts DESC LIMIT 20",(session,symbol)
    ).fetchall()
    vals=[float(r[0]) for r in rows if r[0] is not None and float(r[0])>0]
    if not vals:return None
    base=statistics.median(vals)
    return current_volume/base if base>0 else None

def prior_minute_observation(db,session,symbol):
    return db.execute(
      "SELECT source_ts,change_pct FROM fast_path_v047_observations "
      "WHERE session=? AND symbol=? AND minute_bar_present=1 ORDER BY source_ts DESC LIMIT 1",
      (session,symbol)).fetchone()

def upsert_state(db,session,symbol,now):
    if db.execute("SELECT 1 FROM fast_path_v047_state WHERE session=? AND symbol=?",(session,symbol)).fetchone():return
    db.execute("INSERT INTO fast_path_v047_state(session,symbol,first_seen_ts,last_seen_ts) VALUES(?,?,?,?)",
      (session,symbol,now,now))

def process(db,session):
    latest=db.execute("""
      SELECT e.symbol,e.retrieval_ts,e.change_pct,e.bar_high_pct,e.observed_volume,e.bid,e.ask,e.spread_pct,
             e.minute_bar_present,e.catalyst,s.last_source_ts
      FROM fast_path_events e
      JOIN fast_path_state s ON s.session=e.session AND s.symbol=e.symbol
      JOIN (SELECT symbol,MAX(id) id FROM fast_path_events WHERE session=? GROUP BY symbol) z ON z.id=e.id
      WHERE e.session=?
    """,(session,session)).fetchall()
    new_obs=event_new=flow_pass=flow_reject=0
    for r in latest:
        symbol,retrieval,pct,high_pct,vol,bid,ask,spread,mb,catalyst,source_ts=r
        if not source_ts or pct is None:continue
        if db.execute("SELECT 1 FROM fast_path_v047_observations WHERE session=? AND symbol=? AND source_ts=?",
          (session,symbol,source_ts)).fetchone():continue
        now=retrieval or datetime.now(timezone.utc).isoformat();upsert_state(db,session,symbol,now)
        st=db.execute("""SELECT flow_positive_count,max_high_pct,base_flow_decided,event_seen,
          filtered_flow_seen,first_signal_ts FROM fast_path_v047_state WHERE session=? AND symbol=?""",
          (session,symbol)).fetchone()
        streak=int(st[0] or 0);max_high_before=st[1];base_decided=int(st[2] or 0)
        event_seen=int(st[3] or 0);first_signal=st[5]
        hp=float(high_pct if high_pct is not None else pct)
        early=((max_high_before is None or float(max_high_before)<10) and hp<10)

        # FLOW uses only completed observed minute bars. Missing/trade fallback does not
        # count as negative evidence. Event-time gaps >5m reset persistence.
        if int(mb or 0)==1 and vol is not None and float(vol)>=0:
            prior=prior_minute_observation(db,session,symbol)
            positive=False
            if prior:
                try:
                    prev_ts=datetime.fromisoformat(prior[0].replace("Z","+00:00"))
                    cur_ts=datetime.fromisoformat(source_ts.replace("Z","+00:00"))
                    dt=(cur_ts-prev_ts).total_seconds()/60
                    accel=(float(pct)-float(prior[1]))/dt if dt>0 else None
                    positive=bool(0<dt<=5 and early and 0<float(pct)<10 and accel is not None and accel>0 and float(vol)>0)
                    streak=streak+1 if positive else 0
                except Exception:
                    streak=0
            else:streak=0

        ratio=prior_volume_ratio(db,session,symbol,float(vol or 0)) if int(mb or 0)==1 and vol and float(vol)>0 else None
        event_candidate=bool(catalyst) and early and not event_seen
        base_flow_candidate=bool(not base_decided and int(mb or 0)==1 and early and 0<float(pct)<10 and streak>=2)
        filtered_candidate=bool(base_flow_candidate and ratio is not None and ratio>=THRESHOLD)

        db.execute("""INSERT INTO fast_path_v047_observations
          (session,symbol,source_ts,retrieval_ts,change_pct,bar_high_pct,bar_volume,bid,ask,spread_pct,minute_bar_present,catalyst)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (session,symbol,source_ts,now,pct,hp,vol,bid,ask,spread,int(mb or 0),catalyst or ""))
        new_obs+=1
        new_max=hp if max_high_before is None else max(float(max_high_before),hp)
        sets=["last_seen_ts=?","flow_positive_count=?","max_high_pct=?"];args=[now,streak,new_max]
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
            sets+=["first_signal_ts=?","first_signal_source_ts=?","first_signal_type=?","first_signal_change=?",
                   "signal_bid=?","signal_ask=?","signal_spread_pct=?","signal_minute_bar_present=?"]
            args += [now,source_ts,signal_type,pct,bid,ask,spread,int(mb or 0)]
        args += [session,symbol]
        db.execute("UPDATE fast_path_v047_state SET "+",".join(sets)+" WHERE session=? AND symbol=?",args)
    return {"new_observations":new_obs,"new_events":event_new,"new_filtered_flows":flow_pass,"new_flow_rejects":flow_reject}

def report(db,session,out):
    q=db.execute("""SELECT COUNT(*),SUM(event_seen),SUM(filtered_flow_seen),
      SUM(CASE WHEN first_signal_ts IS NOT NULL THEN 1 ELSE 0 END),
      SUM(CASE WHEN base_flow_decided=1 AND filtered_flow_seen=0 THEN 1 ELSE 0 END)
      FROM fast_path_v047_state WHERE session=?""",(session,)).fetchone()
    counts={"symbols":int(q[0] or 0),"event_seen":int(q[1] or 0),"filtered_flow_seen":int(q[2] or 0),
      "combined_first_signals":int(q[3] or 0),"flow_activity_rejects":int(q[4] or 0)}
    rows=[]
    for r in db.execute("""SELECT symbol,event_seen,event_first_ts,event_first_change,filtered_flow_seen,
      flow_first_ts,flow_first_change,flow_activity_ratio,first_signal_ts,first_signal_source_ts,
      first_signal_type,first_signal_change,signal_bid,signal_ask,signal_spread_pct,signal_minute_bar_present,last_seen_ts
      FROM fast_path_v047_state WHERE session=? AND first_signal_ts IS NOT NULL ORDER BY first_signal_ts""",(session,)):
        rows.append({"symbol":r[0],"event_seen":bool(r[1]),"event_first_ts":r[2],"event_first_change":r[3],
          "filtered_flow_seen":bool(r[4]),"flow_first_ts":r[5],"flow_first_change":r[6],"flow_activity_ratio":r[7],
          "first_signal_ts":r[8],"first_signal_source_ts":r[9],"first_signal_type":r[10],"first_signal_change":r[11],
          "signal_bid":r[12],"signal_ask":r[13],"signal_spread_pct":r[14],"signal_minute_bar_present":bool(r[15]),"last_seen_ts":r[16]})
    spreads=[float(x["signal_spread_pct"]) for x in rows if x["signal_spread_pct"] is not None]
    telemetry={"signal_count":len(rows),"signal_ask_available_rate":(sum(x["signal_ask"] is not None for x in rows)/len(rows) if rows else None),
      "median_signal_spread_pct":statistics.median(spreads) if spreads else None,
      "signal_spread_le_1pct_rate":(sum(x<=1 for x in spreads)/len(spreads) if spreads else None),
      "signal_spread_le_2pct_rate":(sum(x<=2 for x in spreads)/len(spreads) if spreads else None),
      "depth":"UNKNOWN","slippage":"UNKNOWN","halt_state":"UNKNOWN"}
    payload={"status":"SAG-30-v0.4.7-VALIDATED-PROSPECTIVE-OOS-SHADOW","authoritative":False,"buy":False,
      "session":session,"generated_at":datetime.now(timezone.utc).isoformat(),"activity_ratio_threshold":THRESHOLD,
      "counts":counts,"signals":rows,"execution_telemetry":telemetry,
      "note":"Prospective research only. v0.3.3 FROZEN and signal bridge decisions unchanged."}
    Path(out).parent.mkdir(parents=True,exist_ok=True);Path(out).write_text(json.dumps(payload,indent=2,sort_keys=True)+chr(10))
    return payload

def main():
    p=argparse.ArgumentParser();p.add_argument("--db",default="state/radar.sqlite3");p.add_argument("--out",default="state/fast_path_v047_validated_report.json");a=p.parse_args()
    db=sqlite3.connect(a.db);init(db);session=datetime.now(timezone.utc).astimezone(ET).date().isoformat()
    delta=process(db,session);db.commit();payload=report(db,session,a.out);db.commit()
    print(json.dumps({"delta":delta,"counts":payload["counts"],"execution_telemetry":payload["execution_telemetry"]},sort_keys=True))
if __name__=="__main__":main()
