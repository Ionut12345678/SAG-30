"""SAG-30 v0.3.4 CANDIDATE SHADOW evaluator.

Research-only. It never emits production outbox alerts and never changes v0.3.3 state.
"""
import hashlib, json, math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SPEC_PATH=Path("rules/SAG-30-v0.3.4-CANDIDATE-SHADOW.txt")
SPEC_SHA256=hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest() if SPEC_PATH.exists() else None
ET=ZoneInfo("America/New_York")

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS candidate_v034_state(
      symbol TEXT PRIMARY KEY,
      session TEXT NOT NULL,
      state TEXT NOT NULL,
      lane TEXT NOT NULL,
      first_watch_ts TEXT,
      first_watch_pct REAL,
      memory TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS candidate_v034_events(
      observation_id INTEGER PRIMARY KEY,
      evaluated_ts TEXT NOT NULL,
      symbol TEXT NOT NULL,
      session TEXT NOT NULL,
      state TEXT NOT NULL,
      lane TEXT NOT NULL,
      change_pct REAL,
      rvol REAL,
      baseline_samples INTEGER NOT NULL,
      detail TEXT NOT NULL,
      spec_sha256 TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS candidate_v034_signals(
      id INTEGER PRIMARY KEY,
      symbol TEXT NOT NULL,
      observation_id INTEGER UNIQUE NOT NULL,
      retrieval_ts TEXT NOT NULL,
      lane TEXT NOT NULL,
      state TEXT NOT NULL,
      change_pct REAL NOT NULL,
      baseline_close REAL NOT NULL,
      proof TEXT NOT NULL,
      spec_sha256 TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS candidate_v034_milestones(
      signal_id INTEGER NOT NULL,
      target INTEGER NOT NULL,
      observation_id INTEGER NOT NULL,
      retrieval_ts TEXT NOT NULL,
      PRIMARY KEY(signal_id,target)
    );
    """)

def _et_session(ts):
    return datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(ET).date().isoformat()

def _et_minutes(ts):
    d=datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(ET)
    return d.hour*60+d.minute

def _prior_winner_last_five_sessions(db,symbol,observation_id,current_session):
    rows=db.execute(
      "SELECT retrieval_ts,change_pct FROM observations WHERE symbol=? AND id<? AND quality='OK' ORDER BY id DESC LIMIT 500",
      (symbol,observation_id)
    ).fetchall()
    sessions=[]
    winner_sessions=set()
    for ts,pct in rows:
        session=_et_session(ts)
        if session==current_session:
            continue
        if session not in sessions:
            sessions.append(session)
            if len(sessions)>5:
                break
        if pct is not None and pct>=30:
            winner_sessions.add(session)
    return any(s in winner_sessions for s in sessions[:5])

def _lane(db,symbol,observation_id,retrieval_ts):
    if 4*60 <= _et_minutes(retrieval_ts) < 9*60+30:
        return "OVERNIGHT"
    session=_et_session(retrieval_ts)
    return "SECOND_IMPULSE" if _prior_winner_last_five_sessions(db,symbol,observation_id,session) else "FRESH"

def _band(pct):
    if pct < 5: return "EXCELLENT"
    if pct < 10: return "IDEAL"
    if pct < 15: return "EARLY VALID"
    if pct < 20: return "SALVAGE"
    return "LATE"

def evaluate(db,observation_id,evaluated_ts):
    init(db)
    obs=db.execute(
      "SELECT symbol,retrieval_ts,source_ts,quality,price,change_pct,payload FROM observations WHERE id=?",
      (observation_id,)
    ).fetchone()
    if not obs:
        raise ValueError("Unknown observation")
    symbol,retrieval,source,quality,price,pct,raw=obs
    session=_et_session(retrieval)
    shadow_row=db.execute("SELECT payload FROM semantic_shadow WHERE observation_id=?",(observation_id,)).fetchone()
    shadow=json.loads(shadow_row[0]) if shadow_row else {}
    samples=int(shadow.get("same_clock_volume_sample_count") or 0)
    rvol=shadow.get("observed_same_clock_volume_ratio")
    lane=_lane(db,symbol,observation_id,retrieval)

    existing=db.execute(
      "SELECT session,state,lane,first_watch_ts,first_watch_pct,memory FROM candidate_v034_state WHERE symbol=?",
      (symbol,)
    ).fetchone()
    if not existing or existing[0]!=session:
        first_watch_ts=None; first_watch_pct=None; memory={}
    else:
        first_watch_ts,first_watch_pct,memory=existing[3],existing[4],json.loads(existing[5])

    # Candidate milestones are tracked independently and never alter production.
    if quality=="OK" and isinstance(price,(int,float)):
        for signal_id,baseline in db.execute(
          "SELECT id,baseline_close FROM candidate_v034_signals WHERE symbol=? AND retrieval_ts<=?",
          (symbol,retrieval)
        ).fetchall():
            for target in (30,50):
                if price >= baseline*(1+target/100):
                    db.execute(
                      "INSERT OR IGNORE INTO candidate_v034_milestones VALUES(?,?,?,?)",
                      (signal_id,target,observation_id,retrieval)
                    )

    state="C34-DATA_QUALITY"; detail="authoritative observation is not quality=OK"
    if quality=="OK":
        state="C34-LOW"; detail="activity not confirmed on candidate-valid baseline"
        baseline_valid=samples>=5 and isinstance(rvol,(int,float)) and math.isfinite(rvol) and rvol>=0
        activity=baseline_valid and rvol>=3

        if lane!="FRESH":
            state="C34-BLOCKED-LANE"
            detail=f"{lane} tracked but promotion disabled in v0.3.4 candidate revision 1"
        elif activity:
            if first_watch_ts is None:
                first_watch_ts=retrieval; first_watch_pct=pct
            state="C34-WATCH"; detail=f"activity confirmed; RVOL={rvol:.2f}x samples={samples}"

            previous_price=shadow.get("previous_price")
            previous_pct=shadow.get("previous_change_pct")
            price_delta=shadow.get("price_delta")
            pct_delta=shadow.get("change_delta_pp")

            # A failed path may restart prospectively from a later conversion.
            failed_floor=memory.get("conversion_floor")
            if failed_floor is not None and price is not None and price < failed_floor:
                memory={}
                state="C34-FAILED"; detail="price fell below pre-conversion floor"
            if not memory.get("conversion_ts") and all(isinstance(v,(int,float)) for v in (price,pct,previous_price,previous_pct,price_delta,pct_delta)):
                if price_delta>0 and pct_delta>0 and pct<20:
                    memory={
                      "conversion_ts":retrieval,
                      "conversion_source_ts":source,
                      "conversion_price":price,
                      "conversion_pct":pct,
                      "conversion_floor":previous_price,
                      "accepted_ts":None,
                      "accepted_pct":None,
                      "high":price,
                      "previous_price":price,
                      "positive":0,
                      "no_high":0
                    }
                    state="C34-CONVERSION"; detail="directional price progress after confirmed activity"

            elif memory.get("conversion_ts") and retrieval>memory["conversion_ts"]:
                if price < memory["conversion_floor"]:
                    memory={}
                    state="C34-FAILED"; detail="failed acceptance: loss of pre-conversion floor"
                elif not memory.get("accepted_ts"):
                    if price>=memory["conversion_price"]:
                        memory["accepted_ts"]=retrieval
                        memory["accepted_pct"]=pct
                        memory["high"]=max(memory["high"],price)
                        memory["previous_price"]=price
                        state="C34-ACCEPTED"; detail="conversion held on later observation"
                    else:
                        state="C34-WATCH"; detail="waiting for acceptance hold"
                elif retrieval>memory["accepted_ts"]:
                    old_high=memory["high"]
                    new_high=price>old_high
                    rising=price>memory.get("previous_price",memory["conversion_price"]) and new_high
                    memory["positive"]=memory.get("positive",0)+1 if rising else 0
                    memory["no_high"]=0 if new_high else memory.get("no_high",0)+1
                    proof=None
                    if new_high:
                        proof="new observed high after acceptance"
                    if pct-memory["accepted_pct"]>=2:
                        proof="reacceleration >=2pp after acceptance"
                    if memory["positive"]>=2:
                        proof="two positive intervals with rising observed highs"
                    if memory["no_high"]>=2 and not proof:
                        state="C34-WAIT-ABSORPTION"; detail="two observations without a new high"
                    elif proof:
                        state="C34-LATE-SHADOW" if pct>=20 else "C34-HOT-SHADOW"
                        detail=proof
                        payload=json.loads(raw)
                        baseline=float((payload.get("prevDailyBar") or {}).get("c") or 0)
                        if baseline>0:
                            db.execute(
                              "INSERT OR IGNORE INTO candidate_v034_signals(symbol,observation_id,retrieval_ts,lane,state,change_pct,baseline_close,proof,spec_sha256) VALUES(?,?,?,?,?,?,?,?,?)",
                              (symbol,observation_id,retrieval,lane,state,pct,baseline,proof,SPEC_SHA256)
                            )
                        memory["hot"]=True
                    else:
                        state="C34-ACCEPTED"; detail="accepted; waiting for expansion proof"
                    memory["high"]=max(old_high,price)
                    memory["previous_price"]=price

            if memory.get("hot") and state not in ("C34-FAILED","C34-DATA_QUALITY"):
                prior_signal=db.execute(
                  "SELECT state FROM candidate_v034_signals WHERE symbol=? AND retrieval_ts<=? ORDER BY id DESC LIMIT 1",
                  (symbol,retrieval)
                ).fetchone()
                if prior_signal:
                    state=prior_signal[0]
                    detail="candidate signal already established this session"

    db.execute(
      "INSERT OR REPLACE INTO candidate_v034_events(observation_id,evaluated_ts,symbol,session,state,lane,change_pct,rvol,baseline_samples,detail,spec_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
      (observation_id,evaluated_ts,symbol,session,state,lane,pct,rvol if isinstance(rvol,(int,float)) else None,samples,detail,SPEC_SHA256)
    )
    db.execute(
      "INSERT INTO candidate_v034_state(symbol,session,state,lane,first_watch_ts,first_watch_pct,memory) VALUES(?,?,?,?,?,?,?) "
      "ON CONFLICT(symbol) DO UPDATE SET session=excluded.session,state=excluded.state,lane=excluded.lane,"
      "first_watch_ts=excluded.first_watch_ts,first_watch_pct=excluded.first_watch_pct,memory=excluded.memory",
      (symbol,session,state,lane,first_watch_ts,first_watch_pct,json.dumps(memory,sort_keys=True))
    )
    return state
