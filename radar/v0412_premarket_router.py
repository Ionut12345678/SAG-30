"""SAG-30 v0.4.12 EARLY-PREMARKET ROUTING SHADOW.

Best-effort routing only. Never model evidence, never BUY. Uses a public premarket
mover board for discovery and an independent pre/post 1-minute price series for
confirmation. Frozen SAG-30 semantics are untouched.
"""
import argparse,csv,json,re,sqlite3,urllib.request
from datetime import datetime,timezone,time as dtime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET=ZoneInfo('America/New_York')
BOARD='https://www.thehotpennystocks.com/scans/premarket-penny-stocks/'
CHART='https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=5d&includePrePost=true&events=div%2Csplits'
UA={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/json'}
ROW=re.compile(r'<tr><td class="pf-rank">(\\d+)</td><td class="pf-sym"><a[^>]*stock=([A-Z0-9.\\-]+)[^>]*>[^<]+</a></td><td class="pf-name">.*?</td><td class="pf-num">\\$([^<]+)</td><td class="pf-num pf-pos">([0-9.]+)%</td><td class="pf-num">([^<]+)</td></tr>',re.S)

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=20) as r:
        return r.read().decode('utf-8','ignore')

def volnum(s):
    s=s.strip().replace(',','').upper(); m=1
    if s.endswith('K'):m=1e3;s=s[:-1]
    elif s.endswith('M'):m=1e6;s=s[:-1]
    elif s.endswith('B'):m=1e9;s=s[:-1]
    try:return float(s)*m
    except:return 0.0

def universe(path):
    with open(path,newline='') as f:return {r['symbol'].strip().upper() for r in csv.DictReader(f)}

def chart_latest(symbol,day):
    d=json.loads(fetch(CHART.format(symbol=symbol)))['chart']['result'][0]
    gmtoffset=int(d.get('meta',{}).get('gmtoffset',-14400)); tz=timezone(timedelta(seconds=gmtoffset))
    ts=d.get('timestamp') or []; q=(d.get('indicators',{}).get('quote') or [{}])[0]; closes=q.get('close') or []
    prev=[]; today=[]
    for t,c in zip(ts,closes):
        if not c:continue
        dt=datetime.fromtimestamp(t,tz)
        if dt.date().isoformat()<day and dtime(9,30)<=dt.time()<=dtime(16,0):prev.append((dt,float(c)))
        if dt.date().isoformat()==day and dtime(4,0)<=dt.time()<dtime(9,30):today.append((dt,float(c)))
    if not prev or not today:return None
    base=prev[-1][1]; latest=today[-1]; first=today[0]
    return {'base':base,'chart_ts':latest[0].isoformat(),'chart_pct':(latest[1]/base-1)*100,'first_ts':first[0].isoformat(),'first_pct':(first[1]/base-1)*100,'bars':len(today)}

def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS v0412_premarket_route(
      session TEXT NOT NULL, observed_ts TEXT NOT NULL, symbol TEXT NOT NULL,
      source_rank INTEGER NOT NULL, source_pct REAL NOT NULL, source_volume REAL NOT NULL,
      chart_ts TEXT, chart_pct REAL, first_chart_ts TEXT, first_chart_pct REAL,
      status TEXT NOT NULL, reason TEXT NOT NULL,
      PRIMARY KEY(session,observed_ts,symbol))''')
    db.execute('CREATE INDEX IF NOT EXISTS v0412_session_symbol ON v0412_premarket_route(session,symbol,observed_ts)')

def run(db_path,universe_path):
    now=datetime.now(timezone.utc); et=now.astimezone(ET); day=et.date().isoformat()
    out={'status':'INACTIVE','session':day,'observed_ts':now.isoformat(),'routes':[],'rejected':[],'note':'ROUTING SHADOW / NOT BUY / NOT MODEL EVIDENCE'}
    db=sqlite3.connect(db_path);init(db)
    try:
        if et.weekday()>=5 or not (dtime(4,0)<=et.time()<dtime(9,30)):
            out['status']='OUTSIDE_PREMARKET';return out
        html=fetch(BOARD)
        if 'Top Gainers' not in html:raise RuntimeError('premarket board missing Top Gainers')
        allowed=universe(universe_path); rows=[]
        for rank,symbol,price,pct,vol in ROW.findall(html):
            rank=int(rank); pct=float(pct)
            if rank>25 or symbol not in allowed:continue
            rows.append((rank,symbol,pct,volnum(vol)))
        for rank,symbol,source_pct,source_vol in rows[:25]:
            try:c=chart_latest(symbol,day)
            except Exception:c=None
            if not c:
                out['rejected'].append({'symbol':symbol,'reason':'NO_CONFIRMING_1M_CHART','source_pct':source_pct});continue
            cp=float(c['chart_pct']); agreement=abs(cp-source_pct)<=max(10.0,0.50*max(abs(source_pct),1.0))
            if 1.0<=cp<20.0 and agreement:
                status='EARLY_PREMARKET_ROUTE_SHADOW';reason='TOP_GAINER_PLUS_INDEPENDENT_1M_CONFIRMATION'
                out['routes'].append({'symbol':symbol,'rank':rank,'source_pct':source_pct,'source_volume':source_vol,**c})
            else:
                status='PREMARKET_TRACK_ONLY';reason='ALREADY_EXPLODED_OR_SOURCE_DISAGREEMENT'
                out['rejected'].append({'symbol':symbol,'reason':reason,'source_pct':source_pct,'chart_pct':cp,'rank':rank})
            db.execute('INSERT OR REPLACE INTO v0412_premarket_route VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
              (day,now.isoformat(),symbol,rank,source_pct,source_vol,c.get('chart_ts'),cp,c.get('first_ts'),c.get('first_pct'),status,reason))
        out['routes']=sorted(out['routes'],key=lambda x:(x['rank'],abs(x['chart_pct'])))[:5]
        out['status']='PASS' if rows else 'NO_UNIVERSE_MATCHES'
        db.commit();return out
    finally:db.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',default='state/radar.sqlite3');p.add_argument('--universe',default='config/universe.csv');p.add_argument('--out',default='state/v0412_premarket_router_report.json');a=p.parse_args()
    out=run(a.db,a.universe);Path(a.out).write_text(json.dumps(out,indent=2));print(json.dumps(out))
if __name__=='__main__':main()
