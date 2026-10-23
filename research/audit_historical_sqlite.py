#!/usr/bin/env python3
"""Historical SQLite checkpoint audit. Read-only. Fail closed on corrupt or absent data."""
import argparse, gzip, hashlib, json, sqlite3, tempfile
from pathlib import Path

def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def audit(root):
    checkpoint=json.loads((root/"checkpoint.json").read_text())
    parts=[root/p["name"] for p in checkpoint["parts"]]
    for path,meta in zip(parts,checkpoint["parts"]):
        if not path.is_file():raise RuntimeError("MISSING_PART: "+path.name)
        if path.stat().st_size!=meta["bytes"] or digest(path)!=meta["sha256"]:
            raise RuntimeError("PART_HASH_MISMATCH: "+path.name)
    with tempfile.TemporaryDirectory() as tmp:
        packed=Path(tmp)/"radar.sqlite3.gz"
        with packed.open("wb") as target:
            for part in parts:
                with part.open("rb") as source:
                    for block in iter(lambda:source.read(4*1024*1024),b""):target.write(block)
        if packed.stat().st_size!=checkpoint["compressed_bytes"] or digest(packed)!=checkpoint["compressed_sha256"]:
            raise RuntimeError("COMPRESSED_HASH_MISMATCH")
        database=Path(tmp)/"radar.sqlite3"
        with gzip.open(packed,"rb") as source,database.open("wb") as dest:
            for block in iter(lambda:source.read(4*1024*1024),b""):dest.write(block)
        if database.stat().st_size!=checkpoint["database_bytes"] or digest(database)!=checkpoint["database_sha256"]:
            raise RuntimeError("DATABASE_HASH_MISMATCH")
        uri="file:"+str(database)+"?mode=ro"
        con=sqlite3.connect(uri,uri=True)
        try:
            integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
            names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts={}
            for name in checkpoint["table_counts"]:
                if name not in names:raise RuntimeError("MISSING_TABLE: "+name)
                counts[name]=con.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]
            mismatches={k:{"checkpoint":v,"actual":counts[k]} for k,v in checkpoint["table_counts"].items() if counts[k]!=v}
            report={"checkpoint_created_ts":checkpoint["created_ts"],"sqlite_integrity":integrity,
                    "database_sha256_verified":True,"checked_tables":len(counts),
                    "counts":counts,"count_mismatches":mismatches,
                    "experiment_21oct_to_20nov_included":False,"mode":"READ_ONLY_HISTORICAL_AUDIT"}
            # Record only schema metadata, never raw quotes or private observations.
            focus=("scout_history","scout_promotions","multi_engine_scores","observations","evaluations","candidate_v034_events","early_paper_follow_v12")
            schema={}
            for table in focus:
                if table in names:
                    schema[table]=[{"name":row[1],"type":row[2]} for row in con.execute('PRAGMA table_info("'+table+'")')]
            report["research_schema"]=schema
            report["research_note"]="Schema discovery only; no outcome-rate claim, no look-ahead or 30-day experiment mixing."
            # Historical funnel: earliest SCOUT observation inside +3..+10 for each
            # symbol-session, with strictly later promotion evidence only.
            # No future-price outcomes, no performance or BUY interpretation.
            early={}
            session_counts={}
            for session,symbol,ts,pct,selected in con.execute(
                "SELECT session,symbol,retrieval_ts,change_pct,selected "
                "FROM scout_history WHERE session IS NOT NULL AND symbol IS NOT NULL "
                "AND retrieval_ts IS NOT NULL AND change_pct BETWEEN 3 AND 10 "
                "ORDER BY session,symbol,retrieval_ts"):
                key=(session,symbol)
                if key not in early:
                    early[key]={"first_seen":ts,"pct":pct,"selected_at_first":bool(selected)}
                    session_counts[session]=session_counts.get(session,0)+1
            promotions={}
            for symbol,ts in con.execute(
                "SELECT symbol,scout_retrieval_ts FROM scout_promotions "
                "WHERE symbol IS NOT NULL AND scout_retrieval_ts IS NOT NULL "
                "ORDER BY scout_retrieval_ts"):
                promotions.setdefault(symbol,[]).append(ts)
            # Promotion table has no session: restrict to same UTC calendar date,
            # and only after the first timestamp. Conservative, may undercount.
            from bisect import bisect_right
            promoted=0
            initial_selected=0
            for (session,symbol),record in early.items():
                initial_selected+=int(record["selected_at_first"])
                future=promotions.get(symbol,[])
                idx=bisect_right(future,record["first_seen"])
                if idx<len(future) and future[idx][:10]==record["first_seen"][:10]:
                    promoted+=1
            report["historical_scout_funnel"]={
                "definition":"Earliest scout_history observation +3..+10 per symbol-session; strictly later scout_promotions timestamp, same UTC date",
                "candidate_symbol_sessions":len(early),
                "selected_at_first_seen":initial_selected,
                "later_promoted_same_utc_day":promoted,
                "sessions":dict(sorted(session_counts.items())),
                "first_seen_min":min((x["first_seen"] for x in early.values()),default=None),
                "first_seen_max":max((x["first_seen"] for x in early.values()),default=None),
                "limits":"Promotion is not validated opportunity, not subsequent price gain; session mapped conservatively via UTC date; no benchmark or causality claim.",
                "prospective_experiment_included":False}

            if integrity!="ok" or mismatches:raise RuntimeError("SQL_INTEGRITY_OR_COUNT_MISMATCH: "+json.dumps(report))
            return report
        finally:con.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",required=True)
    parser.add_argument("--output",default="historical-sqlite-integrity.json")
    args=parser.parse_args()
    report=audit(Path(args.root))
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"integrity":report["sqlite_integrity"],"tables":report["checked_tables"],"verified":True}))
if __name__=="__main__":main()
