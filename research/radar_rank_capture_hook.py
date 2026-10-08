"""Radar-side hook for capturing actual SCOUT ranks at decision time.

Call record_cycle(candidates, timestamp) BEFORE filtering shortlist/deep.
Each candidate must have symbol, rank, change_pct, selected.
The caller owns durable persistence of returned rows in scout_rank_snapshots.
Never reconstruct rank from future highs or best-of-session scores.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import tempfile

def record_cycle(candidates, timestamp):
    t=datetime.fromisoformat(timestamp.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("timestamp must have timezone")
    ts=t.astimezone(timezone.utc).isoformat()
    rows=[]
    seen=set()
    for c in candidates:
        symbol=c["symbol"]
        if symbol in seen: raise ValueError("duplicate symbol in SCOUT cycle")
        seen.add(symbol)
        rank=c.get("rank")
        if rank is not None and (isinstance(rank,bool) or not isinstance(rank,int) or rank<1):
            raise ValueError("invalid rank")
        rows.append({"ts":ts,"session":ts[:10],"symbol":symbol,
                     "rank":rank,"change_pct":c.get("change_pct"),
                     "selected":bool(c.get("selected",False))})
    return rows

def append_cycle(path, candidates, timestamp):
    """Persist full-cycle observations with atomic replacement and deduplication.

    Must be called by the producer before shortlist filtering. Caller must
    serialize concurrent writers (e.g. GitHub Actions concurrency group).
    """
    target=Path(path)
    rows=record_cycle(candidates,timestamp)
    prior=[]
    if target.exists():
        prior=[json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    keys={(x["session"],x["symbol"],x["ts"]) for x in prior}
    new=[x for x in rows if (x["session"],x["symbol"],x["ts"]) not in keys]
    all_rows=sorted(prior+new,key=lambda x:(x["ts"],x["symbol"]))
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=str(target.parent),prefix=".scout-",suffix=".tmp")
    try:
        with os.fdopen(fd,"w") as out:
            for row in all_rows:
                out.write(json.dumps(row,sort_keys=True)+"\\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name,target)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {"cycle_rows":len(rows),"new_rows":len(new),"stored_rows":len(all_rows)}
