"""Validate a restored prospective ledger before allowing signal attribution."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

def check(path, manifest):
    path, manifest=Path(path),Path(manifest)
    if not path.is_file() or not manifest.is_file():
        return {"ok":False,"reason":"NO_PREVIOUS_STATE"}
    raw=path.read_bytes()
    info=json.loads(manifest.read_text())
    if hashlib.sha256(raw).hexdigest()!=info.get("sha256"):
        return {"ok":False,"reason":"STATE_HASH_MISMATCH"}
    records=[json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    if len(records)!=info.get("records"):
        return {"ok":False,"reason":"STATE_COUNT_MISMATCH"}
    for record in records:
        if record.get("mode")!="prospective":
            return {"ok":False,"reason":"NON_PROSPECTIVE_EVENT"}
        for field in ("first_seen","source_ts"):
            dt=datetime.fromisoformat(record[field].replace("Z","+00:00"))
            if dt.tzinfo is None:
                return {"ok":False,"reason":"NAIVE_TIMESTAMP"}
    return {"ok":True,"reason":"STATE_VERIFIED","records":len(records)}

def seal(path, manifest):
    path,manifest=Path(path),Path(manifest)
    raw=path.read_bytes()
    count=sum(bool(line.strip()) for line in raw.splitlines())
    manifest.write_text(json.dumps({"sha256":hashlib.sha256(raw).hexdigest(),"records":count},sort_keys=True)+"\n")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--seal",action="store_true")
    args=parser.parse_args()
    if args.seal:seal(args.ledger,args.manifest)
    else:
        result=check(args.ledger,args.manifest)
        print("STATE_READBACK",json.dumps(result,sort_keys=True))
        if not result["ok"]:raise SystemExit(2)
