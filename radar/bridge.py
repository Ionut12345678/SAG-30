"""Reliable ChatGPT bridge for prospective SAG-30 outbox events."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS bridge_publications(
        event_key TEXT PRIMARY KEY,
        published_ts TEXT NOT NULL,
        commit_sha TEXT NOT NULL
    )""")

def prepare(db_path, out_path):
    db=sqlite3.connect(db_path)
    ensure_schema(db)
    rows=db.execute("""SELECT o.id,o.event_key,o.created_ts,o.message
                       FROM outbox o LEFT JOIN bridge_publications b ON b.event_key=o.event_key
                       WHERE b.event_key IS NULL ORDER BY o.id""").fetchall()
    db.close()
    if not rows:
        Path(out_path).unlink(missing_ok=True)
        return 1
    events=[{'id':r[0],'event_key':r[1],'created_ts':r[2],'message':r[3]} for r in rows]
    payload={'test':False,'kind':'SAG30_SIGNAL_BATCH','trading_action':'NONE',
             'event_count':len(events),'event_key':events[-1]['event_key'],
             'created_ts':events[-1]['created_ts'],'message':events[-1]['message'],
             'events':events}
    Path(out_path).write_text(json.dumps(payload,indent=2)+'\n')
    print(','.join(e['event_key'] for e in events))
    return 0

def ack(db_path, payload_path, commit_sha):
    payload=json.loads(Path(payload_path).read_text())
    events=payload.get('events') or [payload]
    db=sqlite3.connect(db_path)
    ensure_schema(db)
    now=utcnow()
    for event in events:
        db.execute('INSERT OR IGNORE INTO bridge_publications(event_key,published_ts,commit_sha) VALUES(?,?,?)',
                   (event['event_key'],now,commit_sha))
    db.commit()
    db.close()

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('prepare'); a.add_argument('--db',required=True); a.add_argument('--out',required=True)
    a=sub.add_parser('ack'); a.add_argument('--db',required=True); a.add_argument('--payload',required=True); a.add_argument('--commit',required=True)
    args=p.parse_args()
    if args.cmd=='prepare':
        raise SystemExit(prepare(args.db,args.out))
    ack(args.db,args.payload,args.commit)

if __name__=='__main__':
    main()
