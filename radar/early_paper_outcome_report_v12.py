"""Prospective 7-day early PAPER entry-to-later-trade outcome ledger."""
import argparse,json,sqlite3
from pathlib import Path
from datetime import datetime,timezone,timedelta
def _dt(s):
 try:return datetime.fromisoformat(s.replace("Z","+00:00"))
 except (TypeError,ValueError,AttributeError):return None
def build(path):
 db=sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True);db.row_factory=sqlite3.Row
 has=lambda t:bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone())
 if not has("early_paper_extra_observations"):return {"status":"NO_ENTRIES","entries":[]}
 rows=db.execute("""SELECT e.run_id,e.session,e.symbol,e.quote_retrieved_ts,e.ask,e.discovery_pct
 FROM early_paper_extra_observations e
 WHERE e.screen_stage='EARLY_PAPER_ENTRY_REVIEW' AND e.ask>0
 AND e.run_id=(SELECT MIN(x.run_id) FROM early_paper_extra_observations x
 WHERE x.session=e.session AND x.symbol=e.symbol AND
 x.screen_stage='EARLY_PAPER_ENTRY_REVIEW' AND x.ask>0)
 ORDER BY e.run_id,e.symbol""").fetchall()
 latest=db.execute("SELECT MAX(started) FROM runs").fetchone()[0]
 now=_dt(latest) or datetime.now(timezone.utc)
 entries=[]
 for r in rows:
  x=dict(r);t=_dt(x["quote_retrieved_ts"])
  future=db.execute("""SELECT follow_run_id,observed_ts,source_ts,trade_price,indicative_return_pct
   FROM early_paper_follow_v12 WHERE entry_run_id=? AND symbol=? AND status='FRESH_LATER_TRADE'
   ORDER BY follow_run_id""",(x["run_id"],x["symbol"])).fetchall() if has("early_paper_follow_v12") else []
  returns=[float(z["indicative_return_pct"]) for z in future if z["indicative_return_pct"] is not None]
  x["later_valid_observations"]=len(returns)
  x["max_observed_return_pct"]=max(returns) if returns else None
  x["last_observed_return_pct"]=returns[-1] if returns else None
  x["hit_30_from_ask"]=any(v>=30 for v in returns) if returns else None
  x["hit_50_from_ask"]=any(v>=50 for v in returns) if returns else None
  x["first_future_trade_ts"]=future[0]["source_ts"] if future else None
  x["last_future_trade_ts"]=future[-1]["source_ts"] if future else None
  x["last_future_trade_price"]=future[-1]["trade_price"] if future else None
  x["status"]="OPEN_CENSORED" if t and now-t<=timedelta(days=7) else "WINDOW_ENDED_INCOMPLETE"
  entries.append(x)
 return {"version":"SAG30_EARLY_PAPER_OUTCOMES_V12","status":"PROSPECTIVE_PAPER_NOT_BUY",
  "entries_count":len(entries),"with_future_valid_trades":sum(e["later_valid_observations"]>0 for e in entries),
  "hit30_observed":sum(e["hit_30_from_ask"] is True for e in entries),
  "hit50_observed":sum(e["hit_50_from_ask"] is True for e in entries),
  "entries":entries,
  "caveat":"Entry uses IEX observed ask; subsequent observed trades are NOT executable exit bids. No profit/fill guarantee; partial observations, no intrabar maxima, 7-day censoring."}
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--db",required=True);p.add_argument("--out",required=True)
 a=p.parse_args();Path(a.out).write_text(json.dumps(build(a.db),indent=2))
