"""Lossless SHADOW prototype for splitting gzip SQLite checkpoints into bounded Git blobs.
Does not change the production workflow. Verifies SHA-256 before atomic restore.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

FORMAT = "sag30-checkpoint-shards-v1"
CHUNK_BYTES = 32 * 1024 * 1024

def _digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()

def pack(source, destination, chunk_bytes=CHUNK_BYTES):
    source, destination = Path(source), Path(destination)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("nonempty gzip checkpoint required")
    if not 0 < chunk_bytes <= 50 * 1024 * 1024:
        raise ValueError("chunk_bytes must be between 1 and 50 MiB")
    destination.mkdir(parents=True, exist_ok=True)
    if list(destination.iterdir()):
        raise ValueError("destination must be empty to avoid stale chunks")
    pieces = []
    with source.open("rb") as f:
        for i, data in enumerate(iter(lambda: f.read(chunk_bytes), b"")):
            name = f"checkpoint.part-{i:05d}"
            path = destination / name
            path.write_bytes(data)
            pieces.append({"name": name, "bytes": len(data), "sha256": _digest(path)})
    manifest = {"format": FORMAT, "source_bytes": source.stat().st_size,
                "source_sha256": _digest(source), "chunks": pieces}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest

def unpack(directory, output):
    directory, output = Path(directory), Path(output)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format") != FORMAT or not manifest.get("chunks"):
        raise ValueError("invalid manifest")
    if output.exists():
        raise ValueError("refusing to overwrite existing checkpoint")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".sag30-checkpoint-", dir=output.parent)
    os.close(fd)
    temp_path = Path(temporary)
    try:
        with temp_path.open("wb") as target:
            for i, part in enumerate(manifest["chunks"]):
                expected_name = f"checkpoint.part-{i:05d}"
                if part["name"] != expected_name:
                    raise ValueError("chunk order/name mismatch")
                path = directory / expected_name
                if not path.is_file() or path.stat().st_size != part["bytes"]:
                    raise ValueError("missing or wrong-size chunk: " + expected_name)
                if _digest(path) != part["sha256"]:
                    raise ValueError("corrupt chunk: " + expected_name)
                with path.open("rb") as f:
                    for data in iter(lambda: f.read(1024 * 1024), b""):
                        target.write(data)
        if temp_path.stat().st_size != manifest["source_bytes"] or _digest(temp_path) != manifest["source_sha256"]:
            raise ValueError("reconstructed checkpoint mismatch")
        temp_path.replace(output)
    finally:
        temp_path.unlink(missing_ok=True)
    return manifest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("pack")
    p.add_argument("source")
    p.add_argument("destination")
    p = commands.add_parser("unpack")
    p.add_argument("directory")
    p.add_argument("output")
    args = parser.parse_args()
    result = pack(args.source, args.destination) if args.command == "pack" else unpack(args.directory, args.output)
    print(json.dumps({"status": "verified", "source_bytes": result["source_bytes"],
                      "chunks": len(result["chunks"]), "source_sha256": result["source_sha256"]}))

if __name__ == "__main__":
    main()
