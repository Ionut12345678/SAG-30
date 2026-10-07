"""Build immutable reusable SAG-30 balanced replay dataset.
Infrastructure-only: no model thresholds, signals or BUY semantics.
"""
import argparse,gzip,hashlib,json,os
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from research.fast_path_v041_replay import load_universe,sessions
from research.fast_path_v042_replay import request_json_resilient

ET=ZoneInfo("America/New_York")

def daily_resilient(symbols,start,end,headers,feed):
    out={}
    for off in range(0,len(symbols),100):
        batch=symbols[off:off+100]; token=None
        while True:
            p={"symbols":",".join(batch),"timeframe":"1Day","start":start,"end":end,
               "feed":feed,"limit":10000,"adjustment":"all"}
            if token:p["page_token"]=token
            d=request_json_resilient("/v2/stocks/bars",p,headers)
            for s,b in (d.get("bars") or {}).items():out.setdefault(s,[]).extend(b or [])
            token=d.get("next_page_token")
            if not token:break
    return out

def bounds(date):
    d=datetime.fromisoformat(date).replace(tzinfo=ET)
    return d.replace(hour=4,minute=0,second=0,microsecond=0),d.replace(hour=20,minute=0,second=0,microsecond=0)

def chunks(xs,n):
    for i in range(0,len(xs),n):yield xs[i:i+n]

def fetch_bars_for_date(date,symbols,headers,feed):
    start,end=bounds(date); out=defaultdict(list)
    for batch in chunks(sorted(symbols),50):
        token=None
        while True:
            p={"symbols":",".join(batch),"timeframe":"1Min","start":start.isoformat(),"end":end.isoformat(),
               "feed":feed,"limit":10000,"adjustment":"all"}
            if token:p["page_token"]=token
            d=request_json_resilient("/v2/stocks/bars",p,headers)
            for s,b in (d.get("bars") or {}).items():out[s].extend(b or [])
            token=d.get("next_page_token")
            if not token:break
    return {s:sorted(v,key=lambda x:x["t"]) for s,v in out.items()}

def fetch_news_for_date(date,symbols,headers):
    d=datetime.fromisoformat(date).replace(tzinfo=ET)
    start=(d-timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0)
    end=d.replace(hour=20,minute=0,second=0,microsecond=0)
    out=defaultdict(list)
    wanted=set(symbols)
    for batch in chunks(sorted(symbols),50):
        token=None
        while True:
            p={"symbols":",".join(batch),"start":start.isoformat(),"end":end.isoformat(),
               "limit":50,"sort":"asc","include_content":"false"}
            if token:p["page_token"]=token
            payload=request_json_resilient("/v1beta1/news",p,headers)
            for n in payload.get("news") or []:
                rec={k:n.get(k) for k in ("id","created_at","updated_at","headline","summary","source","symbols","url")}
                for s in n.get("symbols") or []:
                    if s in wanted:out[s].append(rec)
            token=payload.get("next_page_token")
            if not token:break
    return {s:sorted(v,key=lambda x:x.get("created_at") or "") for s,v in out.items()}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--universe",default="config/universe.csv")
    p.add_argument("--out",default="research/cache/sag30_date_matched_v045_dataset.json.gz")
    p.add_argument("--end",default="2026-10-07T05:57:27+00:00")
    p.add_argument("--lookback-days",type=int,default=240)
    p.add_argument("--winners",type=int,default=300);p.add_argument("--nonwinners",type=int,default=300)
    p.add_argument("--feed",default="iex");a=p.parse_args()
    headers={"APCA-API-KEY-ID":os.environ["ALPACA_API_KEY"],"APCA-API-SECRET-KEY":os.environ["ALPACA_SECRET_KEY"]}
    end=datetime.fromisoformat(a.end); start=end-timedelta(days=a.lookback_days)
    dm=daily_resilient(load_universe(a.universe),start.isoformat(),end.isoformat(),headers,a.feed)
    all_winners,all_non=sessions(dm); winners=all_winners[:a.winners]
    need=defaultdict(int)
    for x in winners: need[x["date"]]+=1
    pool=defaultdict(list)
    for x in all_non: pool[x["date"]].append(x)
    non=[]
    for date,count in sorted(need.items()):
        candidates=sorted(pool.get(date,[]),key=lambda x:(x["daily_high_pct"],x["symbol"]),reverse=True)
        if len(candidates)<count:
            raise SystemExit(f"insufficient date-matched hard negatives on {date}: need {count}, have {len(candidates)}")
        non.extend(candidates[:count])
    if len(non)!=a.nonwinners:
        raise SystemExit(f"date-matched nonwinner count {len(non)} != requested {a.nonwinners}")
    got=defaultdict(int)
    for x in non: got[x["date"]]+=1
    if dict(got)!=dict(need):
        raise SystemExit(f"date-match integrity failure: winner dates={dict(need)} nonwinner dates={dict(got)}")
    cohort=[{**x,"label":"winner"} for x in winners]+[{**x,"label":"nonwinner"} for x in non]
    bydate=defaultdict(set)
    for x in cohort:bydate[x["date"]].add(x["symbol"])
    bars={};news={}
    for date in sorted(bydate):
        syms=sorted(bydate[date])
        bd=fetch_bars_for_date(date,syms,headers,a.feed)
        nd=fetch_news_for_date(date,syms,headers)
        for s in syms:
            bars[f"{date}|{s}"]=bd.get(s,[])
            news[f"{date}|{s}"]=nd.get(s,[])
        print(json.dumps({"date":date,"symbols":len(syms),
          "bars":sum(len(bd.get(s,[])) for s in syms),
          "news":sum(len(nd.get(s,[])) for s in syms)},sort_keys=True),flush=True)
    payload={"dataset_version":"SAG30-DATE-MATCHED-v045-CACHE-1","frozen_end":end.isoformat(),
      "lookback_days":a.lookback_days,"feed":a.feed,"winner_count":len(winners),"nonwinner_count":len(non),
      "cohort":cohort,"bars":bars,"news":news,
      "metadata":{"purpose":"immutable reusable historical replay input","model_semantics":"NONE",
        "production_control":"SAG-30 v0.3.3 FROZEN unchanged"}}
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    digest=hashlib.sha256(canonical).hexdigest();payload["dataset_sha256"]=digest
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(out,"wt",encoding="utf-8") as f:json.dump(payload,f,sort_keys=True,separators=(",",":"))
    manifest={"dataset_version":payload["dataset_version"],"dataset_sha256":digest,"frozen_end":end.isoformat(),
      "feed":a.feed,"winner_count":len(winners),"nonwinner_count":len(non),
      "session_dates":sorted(bydate),"bar_count":sum(len(v) for v in bars.values()),
      "news_item_symbol_links":sum(len(v) for v in news.values()),"compressed_bytes":out.stat().st_size}
    Path(str(out)+".manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+chr(10))
    print(json.dumps(manifest,sort_keys=True),flush=True)
if __name__=="__main__":main()
