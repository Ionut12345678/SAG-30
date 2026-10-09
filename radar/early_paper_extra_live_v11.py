"""Additive EARLY PAPER research-only fetch. Does not change frozen BUY gates.

Three additional candidate snapshots per discovery cycle, with actual
retrieval-time quote screen and separately persisted diagnostics.
"""
from datetime import datetime
from urllib.parse import urlencode
from .early_paper_entry_v02 import evaluate as screen

def select(features,production_selected,cap=3):
 selected=set(production_selected)
 eligible=[]
 for symbol,f in features.items():
  p=f.get("change_pct")
  if symbol in selected or not isinstance(p,(int,float)) or isinstance(p,bool) or not 0<=p<10:continue
  eligible.append((symbol,f))
 # Fixed rank, no future labels. Priority turnover first; rank by actual
 # current routing turnover, not historical outcome.
 eligible.sort(key=lambda x:(-float(x[1].get("turnover") or 0),-float(x[1].get("change_pct") or 0),x[0]))
 return [symbol for symbol,_ in eligible[:max(0,min(int(cap),3))]]

def init(db):
 db.execute("""CREATE TABLE IF NOT EXISTS early_paper_extra_observations(
  run_id INTEGER NOT NULL,session TEXT NOT NULL,symbol TEXT NOT NULL,
  discovery_ts TEXT NOT NULL,discovery_pct REAL NOT NULL,
  quote_retrieved_ts TEXT,trade_ts TEXT,quote_ts TEXT,
  bid REAL,ask REAL,trade_price REAL,spread_pct REAL,
  screen_stage TEXT NOT NULL,blockers_json TEXT NOT NULL,
  feed TEXT NOT NULL,PRIMARY KEY(run_id,symbol))""")

def observe(db,run_id,session,features,production_selected,headers,feed,fetch,cap=3):
 import json
 init(db)
 symbols=select(features,production_selected,cap)
 if not symbols:return {"status":"NO_EARLY_EXTRAS","requested":0,"paper_review":0}
 try:
  snapshots,retrieved=fetch(
   "https://data.alpaca.markets/v2/stocks/snapshots?"+urlencode({"symbols":",".join(symbols),"feed":feed}),headers)
 except Exception:
  for symbol in symbols:
   f=features[symbol]
   db.execute("INSERT OR REPLACE INTO early_paper_extra_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    (run_id,session,symbol,f["retrieval_ts"],float(f["change_pct"]),None,None,None,None,None,None,None,
     "FETCH_ERROR",json.dumps(["SHADOW_FETCH_ERROR"]),feed))
  db.commit()
  return {"status":"FETCH_ERROR_SHADOW_ONLY","requested":len(symbols),"paper_review":0}
 passed=0
 for symbol in symbols:
  f=features[symbol];snap=snapshots.get(symbol) or {}
  # Important: price change at the LATER deep quote must be recalculated
  # against prev close; never reuse the earlier discovery change as entry change.
  trade=snap.get("latestTrade") or {}
  quote=snap.get("latestQuote") or {}
  close=(snap.get("prevDailyBar") or {}).get("c")
  price=trade.get("p")
  pct=100*(price/close-1) if isinstance(price,(int,float)) and not isinstance(price,bool) and isinstance(close,(int,float)) and not isinstance(close,bool) and close>0 else None
  r=screen(snap,retrieved,"OK" if snap else "MISSING_SNAPSHOT",pct,True,False,f["retrieval_ts"])
  passed+=int(r["paper_review"])
  db.execute("INSERT OR REPLACE INTO early_paper_extra_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
   (run_id,session,symbol,f["retrieval_ts"],float(f["change_pct"]),retrieved,
    trade.get("t"),quote.get("t"),quote.get("bp"),quote.get("ap"),price,r["spread_pct"],
    r["stage"],json.dumps(r["blockers"]),feed))
 db.commit()
 return {"status":"SHADOW_ONLY_NOT_BUY","requested":len(symbols),"paper_review":passed}
