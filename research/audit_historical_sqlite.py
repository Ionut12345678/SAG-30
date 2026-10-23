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
