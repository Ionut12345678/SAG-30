"""Prospective, research-only evening shortlist with immutable first observation.

Separate from production SCOUT and BUY. All observations must be supplied by the
live collection cycle; historical replay must never call ingest for prospective credit.
"""
import json
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include UTC offset")
    return parsed.astimezone(timezone.utc)


def init(db: sqlite3.Connection):
    db.execute("""CREATE TABLE IF NOT EXISTS evening_scout_shadow (
        session_et TEXT NOT NULL,
        symbol TEXT NOT NULL,
        first_seen_utc TEXT NOT NULL,
        first_price REAL NOT NULL,
        source TEXT NOT NULL,
        source_ts_utc TEXT,
        catalyst TEXT,
        coverage TEXT NOT NULL,
        PRIMARY KEY(session_et, symbol)
    )""")


def ingest(db, *, symbol, price, retrieval_ts_utc, source, source_ts_utc=None,
           catalyst=None, coverage=None):
    """Only genuine live after-hours observations from 16:00-20:00 ET."""
    now = _utc(retrieval_ts_utc)
    et = now.astimezone(ET)
    if not (16 <= et.hour < 20) or et.weekday() >= 5:
        return False
    if not symbol or not source or price is None or float(price) <= 0:
        raise ValueError("symbol, source and positive observed price required")
    if source_ts_utc is not None and _utc(source_ts_utc) > now:
        raise ValueError("future source timestamp")
    init(db)
    # The next US calendar date is an identifier, not a claim of an open market day.
    # Consumer resolves actual next eligible session using its market calendar.
    session = et.date().isoformat()
    cur = db.execute("""INSERT OR IGNORE INTO evening_scout_shadow
        (session_et,symbol,first_seen_utc,first_price,source,source_ts_utc,catalyst,coverage)
        VALUES (?,?,?,?,?,?,?,?)""",
        (session, symbol.upper(), now.isoformat(), float(price), source,
         _utc(source_ts_utc).isoformat() if source_ts_utc else None,
         catalyst, json.dumps(coverage or {}, sort_keys=True)))
    return cur.rowcount == 1


def handoff(db, *, origin_session_et):
    """Read-only handoff. Never reselect or rewrite historical first observations."""
    init(db)
    rows = db.execute("""SELECT symbol,first_seen_utc,first_price,source,
        source_ts_utc,catalyst,coverage FROM evening_scout_shadow
        WHERE session_et=? ORDER BY first_seen_utc,symbol""", (origin_session_et,)).fetchall()
    return [dict(symbol=r[0], first_seen_utc=r[1], first_price=r[2],
                 source=r[3], source_ts_utc=r[4], catalyst=r[5],
                 coverage=json.loads(r[6])) for r in rows]
