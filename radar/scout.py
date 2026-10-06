"""FAST SCOUT routing state for SAG-30.

Infrastructure/discovery only. It never emits production signals and never promotes
v0.3.3/v0.3.4 semantic states. Deep evaluation always uses a fresh later snapshot.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
ACTIVE_STATES=("C34-WATCH","C34-CONVERSION","C34-ACCEPTED","C34-WAIT-ABSORPTION","C34-HOT-SHADOW")

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS scout_state(
      symbol TEXT PRIMARY KEY,
      session TEXT NOT NULL,
      first_seen_ts TEXT NOT NULL,
      first_seen_pct REAL,
      retrieval_ts TEXT NOT NULL,
      source_ts TEXT,
      price REAL NOT NULL,
      change_pct REAL NOT NULL,
      cumulative_volume REAL NOT NULL,
      route_source TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS scout_runs(
      run_id INTEGER PRIMARY KEY,
      started_ts TEXT NOT NULL,
      finished_ts TEXT,
      universe_count INTEGER NOT NULL DEFAULT 0,
      eligible_count INTEGER NOT NULL DEFAULT 0,
      selected_count INTEGER NOT NULL DEFAULT 0,
      sticky_count INTEGER NOT NULL DEFAULT 0,
      fetch_seconds REAL,
      total_seconds REAL
    );
    CREATE TABLE IF NOT EXISTS scout_promotions(
      run_id INTEGER NOT NULL,
      symbol TEXT NOT NULL,
      scout_retrieval_ts TEXT NOT NULL,
      change_pct REAL,
      acceleration_pp_per_min REAL,
      fresh_turnover_impulse_per_min REAL,
      route_source TEXT NOT NULL,
      sticky INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(run_id,symbol)
    );
    CREATE TABLE IF NOT EXISTS scout_history(
      run_id INTEGER NOT NULL,
      session TEXT NOT NULL,
      symbol TEXT NOT NULL,
      retrieval_ts TEXT NOT NULL,
      change_pct REAL NOT NULL,
      acceleration_pp_per_min REAL NOT NULL,
      fresh_turnover_impulse_per_min REAL NOT NULL,
      turnover REAL NOT NULL,
      route_source TEXT NOT NULL,
      rank_change INTEGER NOT NULL,
      rank_acceleration INTEGER NOT NULL,
      rank_impulse INTEGER NOT NULL,
      rank_turnover INTEGER NOT NULL,
      selected INTEGER NOT NULL DEFAULT 0,
      sticky INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(run_id,symbol)
    );
    CREATE INDEX IF NOT EXISTS scout_history_symbol_session ON scout_history(symbol,session,retrieval_ts);
    """)

def _session(ts):
    return datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(ET).date().isoformat()

def momentum_and_update(db,symbol,retrieval_ts,source_ts,price,change_pct,cumulative_volume,route_source):
    """Return routing-only acceleration/impulse from previous scout state and update latest state."""
    init(db)
    session=_session(retrieval_ts)
    prior=db.execute(
      "SELECT session,retrieval_ts,price,change_pct,cumulative_volume,first_seen_ts,first_seen_pct "
      "FROM scout_state WHERE symbol=?",(symbol,)
    ).fetchone()
    accel=0.0
    fresh_volume=0.0
    minutes=None
    first_seen_ts=retrieval_ts
    first_seen_pct=change_pct
    if prior and prior[0]==session:
        first_seen_ts,first_seen_pct=prior[5],prior[6]
        try:
            minutes=(datetime.fromisoformat(retrieval_ts)-datetime.fromisoformat(prior[1])).total_seconds()/60.0
        except (TypeError,ValueError):
            minutes=None
        if minutes and 0 < minutes <= 60:
            accel=(float(change_pct)-float(prior[3]))/minutes
            fresh_volume=max(0.0,float(cumulative_volume)-float(prior[4]))
    db.execute(
      "INSERT INTO scout_state(symbol,session,first_seen_ts,first_seen_pct,retrieval_ts,source_ts,price,change_pct,cumulative_volume,route_source) "
      "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
      "session=excluded.session,first_seen_ts=CASE WHEN scout_state.session=excluded.session THEN scout_state.first_seen_ts ELSE excluded.first_seen_ts END,"
      "first_seen_pct=CASE WHEN scout_state.session=excluded.session THEN scout_state.first_seen_pct ELSE excluded.first_seen_pct END,"
      "retrieval_ts=excluded.retrieval_ts,source_ts=excluded.source_ts,price=excluded.price,change_pct=excluded.change_pct,"
      "cumulative_volume=excluded.cumulative_volume,route_source=excluded.route_source",
      (symbol,session,first_seen_ts,first_seen_pct,retrieval_ts,source_ts,float(price),float(change_pct),float(cumulative_volume),route_source)
    )
    return accel,fresh_volume,minutes

def active_symbols(db, session, limit=50):
    """Keep semantic paths alive; this changes routing retention only, never semantic gates."""
    init(db)
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_v034_state'").fetchone()
    if not exists:
        return []
    rows=db.execute(
      "SELECT symbol,state FROM candidate_v034_state WHERE session=? AND state IN ("+
      ",".join("?" for _ in ACTIVE_STATES)+") ORDER BY "
      "CASE state WHEN 'C34-HOT-SHADOW' THEN 0 WHEN 'C34-ACCEPTED' THEN 1 WHEN 'C34-CONVERSION' THEN 2 "
      "WHEN 'C34-WATCH' THEN 3 ELSE 4 END, symbol LIMIT ?",
      (session,*ACTIVE_STATES,int(limit))
    ).fetchall()
    return [r[0] for r in rows]

def record_promotions(db,run_id,selected,features,sticky):
    init(db)
    sticky=set(sticky)
    for symbol in selected:
        f=features.get(symbol)
        if not f:
            prior=db.execute(
              "SELECT retrieval_ts,change_pct,route_source FROM scout_state WHERE symbol=?",(symbol,)
            ).fetchone()
            if not prior:
                continue
            f={"retrieval_ts":prior[0],"change_pct":prior[1],"acceleration":0.0,"impulse":0.0,"route_source":prior[2]}
        db.execute(
          "INSERT OR REPLACE INTO scout_promotions(run_id,symbol,scout_retrieval_ts,change_pct,acceleration_pp_per_min,"
          "fresh_turnover_impulse_per_min,route_source,sticky) VALUES(?,?,?,?,?,?,?,?)",
          (run_id,symbol,f.get("retrieval_ts"),f.get("change_pct"),f.get("acceleration"),f.get("impulse"),
           f.get("route_source","unknown"),int(symbol in sticky))
        )


def record_universe_history(db,run_id,session,features,selected,sticky):
    """Persist lightweight full-universe routing history for prospective winner-recall audits."""
    init(db)
    if not features:
        return 0
    selected=set(selected); sticky=set(sticky)
    symbols=list(features)
    def ranks(key):
        ordered=sorted(symbols,key=lambda x:(float(features[x].get(key) or 0),x),reverse=True)
        return {symbol:i+1 for i,symbol in enumerate(ordered)}
    rank_change=ranks("change_pct")
    rank_accel=ranks("acceleration")
    rank_impulse=ranks("impulse")
    rank_turnover=ranks("turnover")
    rows=[]
    for symbol in symbols:
        f=features[symbol]
        rows.append((
          run_id,session,symbol,f["retrieval_ts"],float(f["change_pct"]),
          float(f.get("acceleration") or 0),float(f.get("impulse") or 0),float(f.get("turnover") or 0),
          f.get("route_source","unknown"),rank_change[symbol],rank_accel[symbol],
          rank_impulse[symbol],rank_turnover[symbol],int(symbol in selected),int(symbol in sticky)
        ))
    db.executemany(
      "INSERT OR REPLACE INTO scout_history(run_id,session,symbol,retrieval_ts,change_pct,acceleration_pp_per_min,"
      "fresh_turnover_impulse_per_min,turnover,route_source,rank_change,rank_acceleration,rank_impulse,rank_turnover,selected,sticky) "
      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    return len(rows)
