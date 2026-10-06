"""Prospective storage and frozen-evaluator boundary. No model gates are inferred."""
import hashlib
import json
import math
from decimal import Decimal
import sqlite3
from datetime import datetime, timezone

LABEL = 'SAG-30 EARLY RADAR v0.3.3 FROZEN SHADOW - NOT BUY'
STAGES = ['DISCOVERY', 'PRICE CONVERSION', 'ACCEPTANCE/RECLAIM', 'EXPANSION PROOF', 'EARLY-HOT']

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def early_band(pct):
    if pct is None:
        return 'UNKNOWN'
    for ceiling, label in [(5, 'EXCELLENT'), (10, 'IDEAL'), (15, 'EARLY VALID'), (20, 'SALVAGE')]:
        if pct < ceiling:
            return label
    return 'LATE'

def open_db(path):
    db = sqlite3.connect(path)
    db.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL, detail TEXT);
    CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs(id), symbol TEXT NOT NULL,
      retrieval_ts TEXT NOT NULL, source_ts TEXT, request_started_ts TEXT NOT NULL, quality TEXT NOT NULL,
      reason TEXT NOT NULL, price REAL, change_pct REAL, band TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS candidates(symbol TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, expires TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY, observation_id INTEGER UNIQUE REFERENCES observations(id),
      evaluated_ts TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, created_ts TEXT NOT NULL,
      message TEXT NOT NULL, delivered_ts TEXT, attempts INTEGER NOT NULL DEFAULT 0);
    ''')
    return db

def analyze(snapshot, retrieved, max_age):
    trade = snapshot.get('latestTrade') or {}
    previous = snapshot.get('prevDailyBar') or {}
    source = trade.get('t')
    reasons = []
    price, close = trade.get('p'), previous.get('c')
    try:
        stamp = datetime.fromisoformat(source.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('timezone missing')
        age = (datetime.fromisoformat(retrieved) - stamp).total_seconds()
        if age < 0 or age > max_age:
            reasons.append('future_or_stale_source')
    except (TypeError, ValueError, AttributeError):
        reasons.append('missing_or_invalid_source_timestamp')
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        reasons.append('missing_or_invalid_price')
    if not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0 or not previous.get('t'):
        reasons.append('missing_previous_close')
    try:
        previous_time = datetime.fromisoformat(previous.get('t', '').replace('Z','+00:00'))
        retrieval_time = datetime.fromisoformat(retrieved)
        # prevDailyBar is the provider's previous trading bar, not necessarily the
        # previous calendar day (weekends/holidays must not be treated as corrupt).
        # Reject only impossible/future bars or bars so old they cannot represent
        # a recent previous session. The frozen evaluator itself is unchanged.
        if previous_time.tzinfo is None or previous_time >= retrieval_time or (retrieval_time - previous_time).total_seconds() > 7 * 86400:
            reasons.append('invalid_previous_close_time')
    except (ValueError, TypeError):
        reasons.append('invalid_previous_close_time')
    if snapshot.get('data_quality_conflict'):
        reasons.append('source_conflict')
    pct = None if reasons else float((Decimal(str(price)) / Decimal(str(close)) - 1) * 100)
    return source, 'DATA_QUALITY' if reasons else 'OK', ','.join(reasons), price, pct

def record(db, run, symbol, snapshot, started, retrieved, max_age):
    source, quality, reason, price, pct = analyze(snapshot, retrieved, max_age)
    payload = json.dumps(snapshot, sort_keys=True, separators=(',', ':'))
    row = db.execute('INSERT INTO observations(run_id,symbol,retrieval_ts,source_ts,request_started_ts,quality,reason,price,change_pct,band,payload,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        (run, symbol, retrieved, source, started, quality, reason, price, pct, early_band(pct), payload, hashlib.sha256(payload.encode()).hexdigest()))
    db.execute('INSERT INTO evaluations(observation_id,evaluated_ts,status,detail) VALUES(?,?,?,?)',
        (row.lastrowid, utcnow(), 'UNKNOWN', 'Authoritative frozen evaluator unavailable; no stage or early credit awarded.'))
    return quality
