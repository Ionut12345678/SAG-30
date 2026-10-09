"""Independent prospective PAPER follow-up for early accepted quotes.

Only real provider snapshots, never frozen evaluation, signals or orders.
Entry is the observed ask (hypothetical); future latest trades are NOT fills.
"""
import json
from datetime import datetime,timezone,timedelta
from urllib.parse import urlencode

def init(db):
 db.execute("""CREATE TABLE IF NOT EXISTS early_paper_follow_v12(
  entry_run_id INTEGER NOT NULL,session TEXT NOT NULL,symbol TEXT NOT NULL,
  follow_run_id INTEGER NOT NULL,observed_ts TEXT NOT NULL,
  source_ts TEXT,trade_price REAL,entry_ask REAL,
  indicative_return_pct REAL,status TEXT NOT NULL,feed TEXT NOT NULL,
  PRIMARY KEY(entry_run_id,follow_run_id,symbol))""")

def _dt(s):
 try:
  v=datetime.fromisoformat(s.replace("Z","+00:00"))
  return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
 except (TypeError,ValueError,AttributeError):return None

def pending(db,now,days=7,cap=20):
 init(db)
 if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='early_paper_extra_observations'").fetchone():return []
 # First accepted quote per symbol and session is a fixed hypothetical entry.
 rows=db.execute("""SELECT e.run_id,e.session,e.symbol,e.quote_retrieved_ts,e.ask
 FROM early_paper_extra_observations e
 WHERE e.screen_stage='EARLY_PAPER_ENTRY_REVIEW' AND e.ask>0
 AND e.quote_retrieved_ts IS NOT NULL
 AND e.run_id=(SELECT MIN(x.run_id) FROM early_paper_extra_observations x
 WHERE x.session=e.session AND x.symbol=e.symbol AND
 x.screen_stage='EARLY_PAPER_ENTRY_REVIEW' AND x.ask>0)
 ORDER BY e.run_id,e.symbol""").fetchall()
 chosen=[]
 for r in rows:
  run_id,session,symbol,entry_ts,ask=r
  t=_dt(entry_ts)
  if t is None or now<t or now-t>timedelta(days=days):continue
  chosen.append((run_id,session,symbol,entry_ts,float(ask)))
 return chosen[:max(0,int(cap))]

def observe(db,run_id,now,headers,feed,fetch,cap=20):
 init(db);entries=pending(db,now,cap=cap)
 if not entries:return {"status":"NO_OPEN_PAPER_ENTRIES","tracked":0,"fresh":0}
 symbols=sorted({e[2] for e in entries})
 try:
  snapshots,retrieved=fetch("https://data.alpaca.markets/v2/stocks/snapshots?"+urlencode({"symbols":",".join(symbols),"feed":feed}),headers)
 except Exception:
  return {"status":"FOLLOW_FETCH_ERROR","tracked":len(entries),"fresh":0}
 observed=_dt(retrieved);fresh=0
 for entry_run,session,symbol,entry_ts,ask in entries:
  snap=snapshots.get(symbol) or {};trade=snap.get("latestTrade") or {}
  source=trade.get("t");source_dt=_dt(source);entry_dt=_dt(entry_ts)
  price=trade.get("p")
  ok=(isinstance(price,(int,float)) and not isinstance(price,bool) and price>0 and
      observed is not None and source_dt is not None and entry_dt is not None and
      source_dt>entry_dt and 0<=(observed-source_dt).total_seconds()<=900)
  fresh+=int(ok)
  status="FRESH_LATER_TRADE" if ok else "MISSING_OR_STALE_FUTURE_TRADE"
  pct=round(100*(price/ask-1),4) if ok else None
  db.execute("INSERT OR REPLACE INTO early_paper_follow_v12 VALUES(?,?,?,?,?,?,?,?,?,?,?)",
   (entry_run,session,symbol,run_id,retrieved,source,float(price) if isinstance(price,(int,float)) else None,
    ask,pct,status,feed))
 db.commit()
 return {"status":"PAPER_FOLLOW_ONLY_NOT_BUY","tracked":len(entries),"fresh":fresh}
