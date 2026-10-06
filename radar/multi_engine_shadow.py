"""Parallel SHADOW discovery challengers for SAG-30.

Research-only:
1) High-Recall Scout: broad sub-10% precursor net.
2) Ranker: continuous 0-100 cross-sectional score.
3) Dual Engine: unions frozen-independent base routing with top challenger extras.

No production alert and no v0.3.3/v0.3.4 semantic gate is modified.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS multi_engine_scores(
      run_id INTEGER NOT NULL,
      session TEXT NOT NULL,
      symbol TEXT NOT NULL,
      retrieval_ts TEXT NOT NULL,
      change_pct REAL NOT NULL,
      acceleration REAL NOT NULL,
      impulse REAL NOT NULL,
      turnover REAL NOT NULL,
      score REAL NOT NULL,
      score_rank INTEGER NOT NULL,
      high_recall INTEGER NOT NULL DEFAULT 0,
      base_selected INTEGER NOT NULL DEFAULT 0,
      dual_selected INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(run_id,symbol)
    );
    CREATE TABLE IF NOT EXISTS multi_engine_watchpool(
      session TEXT NOT NULL,
      symbol TEXT NOT NULL,
      first_seen_ts TEXT NOT NULL,
      last_seen_ts TEXT NOT NULL,
      first_seen_pct REAL NOT NULL,
      last_seen_pct REAL NOT NULL,
      peak_score REAL NOT NULL,
      seen_count INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY(session,symbol)
    );
    """)

def _percentile(values):
    ordered=sorted(values.items(), key=lambda x:(float(x[1]),x[0]))
    n=max(1,len(ordered)-1)
    return {symbol:(i/n)*100.0 for i,(symbol,_) in enumerate(ordered)}

def evaluate(features, base_selected, extra_limit=20, watch_rank_limit=80, min_change=-10.0, max_change=10.0):
    """Return continuous scores plus a high-recall extra set.

    We intentionally use broad, orthogonal routing evidence and no semantic HOT gates.
    """
    pool={
      s:f for s,f in features.items()
      if isinstance(f.get("change_pct"),(int,float))
      and min_change <= float(f["change_pct"]) < max_change
    }
    if not pool:
        return {},[],[]
    accel={s:max(0.0,float(f.get("acceleration") or 0)) for s,f in pool.items()}
    impulse={s:max(0.0,float(f.get("impulse") or 0)) for s,f in pool.items()}
    turnover={s:max(0.0,float(f.get("turnover") or 0)) for s,f in pool.items()}
    change={s:float(f.get("change_pct") or 0) for s,f in pool.items()}
    pa=_percentile(accel); pi=_percentile(impulse); pt=_percentile(turnover); pc=_percentile(change)
    scores={}
    for s in pool:
        # Rank-based to avoid unit-scale domination. Weights are challenger hypotheses, not production gates.
        score=0.35*pa[s]+0.30*pi[s]+0.20*pt[s]+0.15*pc[s]
        evidence_families=sum([
          accel[s] > 0,
          impulse[s] > 0,
          pt[s] >= 95.0,
          change[s] > 2.0,
        ])
        scores[s]={
          "score":score,"accel_pctile":pa[s],"impulse_pctile":pi[s],
          "turnover_pctile":pt[s],"change_pctile":pc[s],
          "evidence_families":evidence_families,
        }
    ranked=sorted(scores,key=lambda s:(scores[s]["score"],s),reverse=True)
    rank={s:i+1 for i,s in enumerate(ranked)}
    # High recall means at least one live precursor family OR extreme turnover.
    high_recall=[s for s in ranked if scores[s]["evidence_families"]>=1 and rank[s] <= int(watch_rank_limit)]
    base=set(base_selected)
    extras=[s for s in high_recall if s not in base][:int(extra_limit)]
    for s in scores:
        scores[s]["rank"]=rank[s]
        scores[s]["high_recall"]=s in high_recall
        scores[s]["dual_selected"]=s in extras
    return scores,high_recall,extras

def record(db,run_id,session,features,scores,base_selected,extras):
    init(db)
    base=set(base_selected); extras=set(extras)
    rows=[]
    for symbol,score in scores.items():
        f=features[symbol]
        rows.append((
          run_id,session,symbol,f["retrieval_ts"],float(f["change_pct"]),
          float(f.get("acceleration") or 0),float(f.get("impulse") or 0),float(f.get("turnover") or 0),
          float(score["score"]),int(score["rank"]),int(score["high_recall"]),
          int(symbol in base),int(symbol in extras)
        ))
        if score["high_recall"]:
            db.execute(
              "INSERT INTO multi_engine_watchpool(session,symbol,first_seen_ts,last_seen_ts,first_seen_pct,last_seen_pct,peak_score,seen_count) "
              "VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(session,symbol) DO UPDATE SET "
              "last_seen_ts=excluded.last_seen_ts,last_seen_pct=excluded.last_seen_pct,"
              "peak_score=MAX(multi_engine_watchpool.peak_score,excluded.peak_score),"
              "seen_count=multi_engine_watchpool.seen_count+1",
              (session,symbol,f["retrieval_ts"],f["retrieval_ts"],float(f["change_pct"]),float(f["change_pct"]),float(score["score"]))
            )
    db.executemany(
      "INSERT OR REPLACE INTO multi_engine_scores(run_id,session,symbol,retrieval_ts,change_pct,acceleration,impulse,turnover,"
      "score,score_rank,high_recall,base_selected,dual_selected) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",rows
    )
    return len(rows)

def watchpool_symbols(db,session,limit=30,min_seen=2):
    init(db)
    rows=db.execute(
      "SELECT symbol FROM multi_engine_watchpool WHERE session=? AND seen_count>=? "
      "ORDER BY peak_score DESC,last_seen_ts DESC LIMIT ?",
      (session,int(min_seen),int(limit))
    ).fetchall()
    return [r[0] for r in rows]
