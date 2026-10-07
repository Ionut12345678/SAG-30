"""Research report for SAG-30 v0.3.4 CANDIDATE SHADOW."""
import argparse, json, sqlite3
from bisect import bisect_right
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

INTERESTING_STATES=("C34-WATCH","C34-CONVERSION","C34-ACCEPTED","C34-WAIT-ABSORPTION","C34-HOT-SHADOW","C34-LATE-SHADOW")
STATE_PRIORITY={"C34-HOT-SHADOW":0,"C34-ACCEPTED":1,"C34-CONVERSION":2,"C34-WATCH":3,"C34-WAIT-ABSORPTION":4,"C34-LATE-SHADOW":5}

def _table_exists(db,name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None

def _band(pct):
    if pct is None: return "UNKNOWN"
    if pct < 5: return "EXCELLENT"
    if pct < 10: return "IDEAL"
    if pct < 15: return "EARLY_VALID"
    if pct < 20: return "SALVAGE"
    return "LATE"

def _observation_timeline(db):
    """Load valid prospective observations once; avoid thousands of repeated SQLite range scans."""
    timeline={}
    for symbol,ts,pct in db.execute(
        "SELECT symbol,retrieval_ts,change_pct FROM observations "
        "WHERE quality='OK' AND change_pct IS NOT NULL ORDER BY symbol,retrieval_ts"
    ):
        dt=datetime.fromisoformat(ts.replace("Z","+00:00"))
        bucket=timeline.setdefault(symbol,{"times":[],"values":[],"raw":[]})
        bucket["times"].append(dt)
        bucket["values"].append(float(pct))
        bucket["raw"].append(ts)
    return timeline

def _future_window(timeline, symbol, retrieval_ts, minutes):
    bucket=timeline.get(symbol)
    if not bucket:
        return []
    start=datetime.fromisoformat(retrieval_ts.replace("Z","+00:00"))
    end=start+timedelta(minutes=minutes)
    lo=bisect_right(bucket["times"],start)
    hi=bisect_right(bucket["times"],end)
    return list(zip(bucket["raw"][lo:hi],bucket["values"][lo:hi]))

def _outcome_windows(rows, timeline):
    result={}
    for state in ("C34-WATCH","C34-CONVERSION","C34-ACCEPTED","C34-HOT-SHADOW"):
        subset=[r for r in rows if r["state"]==state]
        stats={}
        for minutes in (15,30,60):
            maxima=[]
            hit30=hit50=0
            for r in subset:
                follow=_future_window(timeline,r["symbol"],r["retrieval_ts"],minutes)
                if follow:
                    m=max(v for _,v in follow)
                    maxima.append(m)
                    hit30 += int(m>=30)
                    hit50 += int(m>=50)
            stats[f"plus_{minutes}m"]={
                "events_with_followup":len(maxima),
                "median_max_change_pct":median(maxima) if maxima else None,
                "hit_30":hit30,
                "hit_50":hit50,
            }
        result[state]=stats
    return result

def _winner_path_audit(rows, timeline):
    """Identify WATCH events that subsequently reached +30/+50 without repeated DB scans."""
    winners=[]
    by_symbol_session={}
    for r in rows:
        by_symbol_session.setdefault((r["symbol"],r["session"]),[]).append(r)
    for r in rows:
        if r["state"]!="C34-WATCH":
            continue
        follow=_future_window(timeline,r["symbol"],r["retrieval_ts"],60)
        if not follow:
            continue
        max_pct=max(v for _,v in follow)
        if max_pct < 30:
            continue
        path=[
            {
              "state":p["state"],"retrieval_ts":p["retrieval_ts"],"change_pct":p["change_pct"],
              "rvol":p["rvol"],"baseline_samples":p["baseline_samples"],"detail":p["detail"]
            }
            for p in by_symbol_session.get((r["symbol"],r["session"]),[])
            if p["retrieval_ts"]>=r["retrieval_ts"]
        ]
        first30=next((ts for ts,pct in follow if pct>=30),None)
        first50=next((ts for ts,pct in follow if pct>=50),None)
        winners.append({
          "symbol":r["symbol"],
          "watch_retrieval_ts":r["retrieval_ts"],
          "watch_change_pct":r["change_pct"],
          "watch_rvol":r["rvol"],
          "watch_baseline_samples":r["baseline_samples"],
          "max_change_pct_next_60m":max_pct,
          "first_30_ts":first30,
          "first_50_ts":first50,
          "reached_50":first50 is not None,
          "path_after_watch":path[:20]
        })
    winners.sort(key=lambda x:(not x["reached_50"],-x["max_change_pct_next_60m"]))
    return winners[:50]

def _r2_summary(db, latest_run_id):
    if not _table_exists(db,"candidate_v034r2_events"):
        return {"status":"NO_DATA"}
    states=dict(db.execute("SELECT state,COUNT(*) FROM candidate_v034r2_events GROUP BY state").fetchall())
    first=db.execute(
      "SELECT first_watch_pct FROM candidate_v034r2_state WHERE first_watch_ts IS NOT NULL AND first_watch_pct IS NOT NULL"
    ).fetchall()
    pcts=[float(x[0]) for x in first]
    bands={}
    for pct in pcts:
        b=_band(pct); bands[b]=bands.get(b,0)+1
    signals=db.execute(
      "SELECT symbol,retrieval_ts,state,change_pct,proof FROM candidate_v034r2_signals ORDER BY id"
    ).fetchall() if _table_exists(db,"candidate_v034r2_signals") else []
    frontier=[]
    if latest_run_id is not None:
        rows=db.execute(
          "SELECT c.symbol,c.state,c.change_pct,c.rvol,c.baseline_samples,c.detail,o.retrieval_ts "
          "FROM candidate_v034r2_events c JOIN observations o ON o.id=c.observation_id "
          "WHERE o.run_id=? ORDER BY c.observation_id",(latest_run_id,)
        ).fetchall()
        frontier=[
          {"symbol":x[0],"state":x[1],"change_pct":x[2],"rvol":x[3],"baseline_samples":x[4],"detail":x[5],"retrieval_ts":x[6]}
          for x in rows if x[1] in ("C34R2-WATCH","C34R2-CONVERSION","C34R2-ACCEPTED","C34R2-WAIT-ABSORPTION","C34R2-HOT-SHADOW","C34R2-LATE-SHADOW")
        ]
    return {
      "status":"CANDIDATE_SHADOW_CHALLENGER",
      "version":"SAG-30 v0.3.4r2",
      "states":states,
      "first_watch":{
        "symbols":len(pcts),
        "mean_pct":sum(pcts)/len(pcts) if pcts else None,
        "median_pct":median(pcts) if pcts else None,
        "bands":bands
      },
      "signals":{
        "total":len(signals),
        "negative_change_signals":sum(1 for x in signals if x[3] < 0),
        "recent":[{"symbol":x[0],"retrieval_ts":x[1],"state":x[2],"change_pct":x[3],"proof":x[4]} for x in signals[-50:]]
      },
      "current_frontier":frontier[:50]
    }


def build(db_path):
    db=sqlite3.connect(db_path)
    try:
        if not _table_exists(db,"candidate_v034_events"):
            return {"status":"NO_CANDIDATE_DATA","authoritative":False}

        states=dict(db.execute("SELECT state,COUNT(*) FROM candidate_v034_events GROUP BY state").fetchall())
        lanes=dict(db.execute("SELECT lane,COUNT(*) FROM candidate_v034_events GROUP BY lane").fetchall())
        event_rows=[
            {
              "observation_id":r[0],"symbol":r[1],"session":r[2],"state":r[3],"lane":r[4],
              "change_pct":r[5],"rvol":r[6],"baseline_samples":r[7],"detail":r[8],"retrieval_ts":r[9]
            }
            for r in db.execute(
                "SELECT c.observation_id,c.symbol,c.session,c.state,c.lane,c.change_pct,c.rvol,c.baseline_samples,c.detail,o.retrieval_ts "
                "FROM candidate_v034_events c JOIN observations o ON o.id=c.observation_id ORDER BY c.observation_id"
            )
        ]

        latest_run=db.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        latest_run_id=latest_run[0] if latest_run else None
        frontier=[]
        if latest_run_id is not None:
            current=[
                {
                  "symbol":r[0],"state":r[1],"lane":r[2],"change_pct":r[3],"rvol":r[4],
                  "baseline_samples":r[5],"detail":r[6],"retrieval_ts":r[7]
                }
                for r in db.execute(
                    "SELECT c.symbol,c.state,c.lane,c.change_pct,c.rvol,c.baseline_samples,c.detail,o.retrieval_ts "
                    "FROM candidate_v034_events c JOIN observations o ON o.id=c.observation_id "
                    "WHERE o.run_id=? ORDER BY c.observation_id",(latest_run_id,)
                )
            ]
            newest={}
            for row in current:
                newest[row["symbol"]]=row
            frontier=[v for v in newest.values() if v["state"] in INTERESTING_STATES]
            frontier.sort(key=lambda r:(STATE_PRIORITY.get(r["state"],99),-(r["change_pct"] if isinstance(r["change_pct"],(int,float)) else -999)))

        scout_to_deep=[]
        if latest_run_id is not None and _table_exists(db,"scout_promotions"):
            promotions=db.execute(
              "SELECT symbol,scout_retrieval_ts,change_pct,acceleration_pp_per_min,fresh_turnover_impulse_per_min,route_source,sticky "
              "FROM scout_promotions WHERE run_id=? ORDER BY sticky DESC, symbol",(latest_run_id,)
            ).fetchall()
            for p in promotions:
                deep=db.execute(
                  "SELECT c.state,c.change_pct,c.rvol,c.baseline_samples,o.retrieval_ts "
                  "FROM candidate_v034_events c JOIN observations o ON o.id=c.observation_id "
                  "WHERE o.run_id=? AND c.symbol=? ORDER BY c.observation_id DESC LIMIT 1",
                  (latest_run_id,p[0])
                ).fetchone()
                scout_to_deep.append({
                  "symbol":p[0],"scout_ts":p[1],"scout_change_pct":p[2],
                  "acceleration_pp_per_min":p[3],"fresh_turnover_impulse_per_min":p[4],
                  "route_source":p[5],"sticky":bool(p[6]),
                  "deep_state":deep[0] if deep else None,
                  "deep_change_pct":deep[1] if deep else None,
                  "deep_rvol":deep[2] if deep else None,
                  "deep_baseline_samples":deep[3] if deep else None,
                  "deep_retrieval_ts":deep[4] if deep else None,
                })

        signals=db.execute("SELECT id,symbol,retrieval_ts,lane,state,change_pct,proof FROM candidate_v034_signals ORDER BY id").fetchall() if _table_exists(db,"candidate_v034_signals") else []
        milestone_counts={30:0,50:0}
        if _table_exists(db,"candidate_v034_milestones"):
            for target,count in db.execute("SELECT target,COUNT(DISTINCT signal_id) FROM candidate_v034_milestones GROUP BY target"):
                milestone_counts[int(target)]=int(count)

        first_watch_rows=db.execute(
            "SELECT symbol,first_watch_pct FROM candidate_v034_state WHERE first_watch_ts IS NOT NULL AND first_watch_pct IS NOT NULL"
        ).fetchall()
        first_watch_pcts=[float(r[1]) for r in first_watch_rows]
        first_watch_bands={}
        for pct in first_watch_pcts:
            b=_band(pct); first_watch_bands[b]=first_watch_bands.get(b,0)+1

        baseline=db.execute(
          "SELECT COUNT(*),SUM(CASE WHEN baseline_samples>=5 THEN 1 ELSE 0 END),"
          "SUM(CASE WHEN rvol>=3 THEN 1 ELSE 0 END),SUM(CASE WHEN rvol>=10 THEN 1 ELSE 0 END),"
          "SUM(CASE WHEN baseline_samples BETWEEN 5 AND 9 THEN 1 ELSE 0 END),"
          "SUM(CASE WHEN baseline_samples BETWEEN 10 AND 19 THEN 1 ELSE 0 END),"
          "SUM(CASE WHEN baseline_samples>=20 THEN 1 ELSE 0 END) "
          "FROM candidate_v034_events"
        ).fetchone()

        timeline=_observation_timeline(db)

        return {
          "status":"CANDIDATE_SHADOW_ONLY",
          "authoritative":False,
          "version":"SAG-30 v0.3.4 CANDIDATE SHADOW rev1",
          "latest_run_id":latest_run_id,
          "events":sum(states.values()),
          "states":states,
          "lanes":lanes,
          "current_frontier":frontier[:50],
          "scout_to_deep":scout_to_deep[:60],
          "challenger_r2":_r2_summary(db,latest_run_id),
          "baseline":{
            "events_with_candidate_valid_sample_count":int(baseline[1] or 0),
            "events_rvol_ge_3":int(baseline[2] or 0),
            "events_rvol_ge_10_saturated":int(baseline[3] or 0),
            "sample_coverage_5_9":int(baseline[4] or 0),
            "sample_coverage_10_19":int(baseline[5] or 0),
            "sample_coverage_20_plus":int(baseline[6] or 0)
          },
          "first_watch":{
            "symbols":len(first_watch_pcts),
            "mean_pct":sum(first_watch_pcts)/len(first_watch_pcts) if first_watch_pcts else None,
            "median_pct":median(first_watch_pcts) if first_watch_pcts else None,
            "bands":first_watch_bands
          },
          "forward_outcomes":_outcome_windows(event_rows,timeline),
          "winner_path_audit":_winner_path_audit(event_rows,timeline),
          "signals":{
            "total":len(signals),
            "plus_30_reached":milestone_counts[30],
            "plus_50_reached":milestone_counts[50],
            "recent":[
              {"id":r[0],"symbol":r[1],"retrieval_ts":r[2],"lane":r[3],"state":r[4],"change_pct":r[5],"proof":r[6]}
              for r in signals[-50:]
            ]
          },
          "warning":"Research-only candidate. Forward outcomes are retrospective analytics from observations strictly after each event; they never alter or backdate candidate state. v0.3.3 FROZEN remains authoritative."
        }
    finally:
        db.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True); p.add_argument("--out",required=True)
    a=p.parse_args()
    payload=build(a.db)
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,sort_keys=True))

if __name__=="__main__":
    main()
