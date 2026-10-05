"""Export raw prospective audit plus conservative, explicitly defined metrics."""
import csv
import json
import os
import statistics
from datetime import datetime
from pathlib import Path
from .core import open_db
from .model import init

def report(db):
    init(db)
    observations = db.execute('SELECT symbol,retrieval_ts FROM observations ORDER BY id').fetchall()
    last, gaps = {}, []
    for symbol, stamp in observations:
        current = datetime.fromisoformat(stamp)
        if symbol in last and current.date() == last[symbol].date():
            gaps.append((current-last[symbol]).total_seconds())
        last[symbol] = current
    signals = db.execute('SELECT id,lane,change_pct,band,retrieval_ts FROM signals WHERE replay=0').fetchall()
    first = [row[0] for row in db.execute('SELECT first_radar_pct FROM model_state WHERE first_radar_pct IS NOT NULL')]
    lead = {}
    for target in (30,50):
        values = [(datetime.fromisoformat(hit)-datetime.fromisoformat(start)).total_seconds() for start,hit in db.execute('SELECT s.retrieval_ts,m.retrieval_ts FROM signals s JOIN milestones m ON s.id=m.signal_id WHERE s.replay=0 AND m.target=?',(target,))]
        lead[str(target)] = {'observed_hits':len(values),'median_lead_seconds':statistics.median(values) if values else None}
    return {'prospective_hot_count':len(signals),'by_lane':{lane:sum(s[1]==lane for s in signals) for lane in ('FRESH','SECOND_IMPULSE','OVERNIGHT')},
        'hot_below_10':sum(s[2]<10 for s in signals),'hot_below_15':sum(s[2]<15 for s in signals),
        'salvage_15_to_20':sum(15<=s[2]<20 for s in signals),'late_zero_early_credit':sum(s[2]>=20 for s in signals),
        'median_first_radar_seen_pct':statistics.median(first) if first else None,'observed_outcomes':lead,
        'observation_gap_seconds':gaps,'data_quality_observations':db.execute("SELECT count(*) FROM observations WHERE quality!='OK'").fetchone()[0],
        'false_HOT':'UNKNOWN: frozen spec defines no failure horizon',
        'source_discovery_misses':'UNKNOWN: requires independent coverage benchmark',
        'model_misses':'UNKNOWN: requires independently adjudicated frozen gate evidence',
        'cadence_misses':'Inspect actual gaps against requested cadence; overnight/session breaks are not missed scans'}

if __name__ == '__main__':
    path = Path(os.getenv('RADAR_DB','state/radar.sqlite3'))
    if not path.is_file():
        raise SystemExit('No audit database yet; run collection first or set RADAR_DB.')
    db = open_db(path)
    output = Path('state/export')
    output.mkdir(parents=True,exist_ok=True)
    for table in ('runs','observations','evaluations','model_state','signals','milestones','evidence'):
        init(db)
        cursor = db.execute('SELECT * FROM '+table)
        with (output/(table+'.csv')).open('w',newline='') as file:
            writer = csv.writer(file)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(cursor)
    (output/'metrics.json').write_text(json.dumps(report(db),indent=2))
    print('Audit exports written to state/export (no credentials)')
