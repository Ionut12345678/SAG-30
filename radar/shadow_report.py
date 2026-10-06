"""Research-only calibration report for semantic SHADOW telemetry.

No v0.3.3 FROZEN gate is promoted or modified here.
"""
import argparse, json, sqlite3
from pathlib import Path
from statistics import median

def _pct(values, q):
    values=sorted(v for v in values if isinstance(v,(int,float)))
    if not values: return None
    idx=min(len(values)-1, max(0, round((len(values)-1)*q)))
    return values[idx]

def build(db_path):
    db=sqlite3.connect(db_path)
    try:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='semantic_shadow'").fetchone()
        if not exists:
            return {"status":"NO_SHADOW_DATA","authoritative":False,"packets":0}
        rows=[json.loads(r[0]) for r in db.execute("SELECT payload FROM semantic_shadow ORDER BY observation_id")]
        ratios=[r.get("observed_same_clock_volume_ratio") for r in rows if isinstance(r.get("observed_same_clock_volume_ratio"),(int,float))]
        samples=[int(r.get("same_clock_volume_sample_count") or 0) for r in rows]
        return {
          "status":"SHADOW_ONLY",
          "authoritative":False,
          "packets":len(rows),
          "coverage":{
            "history_ge_1":sum(n>=1 for n in samples),
            "history_ge_3":sum(n>=3 for n in samples),
            "history_ge_5":sum(n>=5 for n in samples),
            "history_ge_10":sum(n>=10 for n in samples),
            "volume_ratio_available":len(ratios),
          },
          "path_events":{
            "new_observed_high":sum(r.get("new_observed_high") is True for r in rows),
            "two_positive_intervals":sum(int(r.get("consecutive_positive_intervals") or 0)>=2 for r in rows),
          },
          "volume_ratio_distribution":{
            "median":median(ratios) if ratios else None,
            "p75":_pct(ratios,0.75),
            "p90":_pct(ratios,0.90),
            "p95":_pct(ratios,0.95),
          },
          "warning":"Research telemetry only. No candidate baseline, threshold, or semantic gate is authorized for v0.3.3 FROZEN."
        }
    finally:
        db.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True); p.add_argument("--out",required=True)
    a=p.parse_args()
    result=build(a.db)
    Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
