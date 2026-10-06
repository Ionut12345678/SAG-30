"""Historical 300-winner stress test for SAG-30.

Research-only. Uses Alpaca historical IEX bars and news to:
- identify recent +30%/+50% winner sessions from the configured universe,
- reconstruct 5-minute paths,
- measure first +2/+5/+10/+30/+50 crossings and lead times,
- classify whether a pre-move news/event catalyst was available.

Important limitations:
- current-universe survivorship bias,
- IEX feed is partial-market coverage,
- historical market-cap/float are not reconstructed,
- this does not replay the full live ranker cross-section.
"""
import argparse, csv, json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ET=ZoneInfo("America/New_York")
API="https://data.alpaca.markets"

CATALYST_RULES=[
 ("ANTI_DILUTION_BUYBACK",("buyback","repurchase","at-the-market","atm","suspend")),
 ("MNA",("merger","acquisition","acquire","strategic combination","business combination")),
 ("CONTRACT",("contract","agreement","award","order","purchase order","customer")),
 ("FDA_CLINICAL",("fda","clinical","trial","phase 1","phase 2","phase 3","topline")),
 ("GOV_DEFENSE",("department of defense","dod","government","federal","army","navy","air force","grant")),
 ("FINANCING",("offering","registered direct","private placement","financing","securities purchase")),
 ("EARNINGS",("earnings","results","revenue","quarter","guidance")),
 ("PATENT_TECH",("patent","technology","platform","ai ","artificial intelligence","blockchain")),
]

def request_json(path, params, headers, retries=6):
    url=API+path+"?"+urlencode(params)
    for attempt in range(retries):
        try:
            with urlopen(Request(url,headers=headers),timeout=45) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==retries-1:
                raise
            retry=e.headers.get("Retry-After")
            wait=float(retry) if retry else min(2**attempt,20)
            time.sleep(wait)
    raise RuntimeError("request retries exhausted")

def load_universe(path):
    with open(path,newline="") as f:
        return sorted({r["symbol"].strip().upper() for r in csv.DictReader(f) if r.get("symbol")})

def historical_daily(symbols,start,end,headers,feed):
    out={}
    for off in range(0,len(symbols),100):
        batch=symbols[off:off+100]
        token=None
        while True:
            params={"symbols":",".join(batch),"timeframe":"1Day","start":start,"end":end,"feed":feed,"limit":10000,"adjustment":"all"}
            if token: params["page_token"]=token
            payload=request_json("/v2/stocks/bars",params,headers)
            for s,bars in (payload.get("bars") or {}).items():
                out.setdefault(s,[]).extend(bars)
            token=payload.get("next_page_token")
            if not token: break
    return out

def candidate_events(daily):
    events=[]
    for symbol,bars in daily.items():
        bars=sorted(bars,key=lambda x:x["t"])
        prev_close=None
        for b in bars:
            if prev_close and prev_close>0:
                high=float(b.get("h") or 0)
                if high>0:
                    pct=(high/prev_close-1)*100
                    if pct>=30:
                        events.append({
                          "symbol":symbol,"date":b["t"][:10],"prev_close":prev_close,
                          "daily_high":high,"daily_high_pct":pct
                        })
            close=float(b.get("c") or 0)
            if close>0: prev_close=close
    return sorted(events,key=lambda e:(e["date"],e["daily_high_pct"]),reverse=True)

def session_bounds(date_str):
    d=datetime.fromisoformat(date_str).replace(tzinfo=ET)
    start=d.replace(hour=4,minute=0,second=0,microsecond=0)
    end=d.replace(hour=20,minute=0,second=0,microsecond=0)
    return start.isoformat(),end.isoformat()

def intraday_one(event,headers,feed):
    start,end=session_bounds(event["date"])
    payload=request_json(f'/v2/stocks/{event["symbol"]}/bars',{
      "timeframe":"5Min","start":start,"end":end,"feed":feed,"limit":10000,"adjustment":"all"
    },headers)
    bars=payload.get("bars") or []
    prev=event["prev_close"]
    thresholds=[2,5,10,30,50]
    first={str(x):None for x in thresholds}
    max_pct=None
    max_ts=None
    observations=[]
    prior_pct=None
    prior_vol=None
    prior_ts=None
    for b in sorted(bars,key=lambda x:x["t"]):
        high=float(b.get("h") or 0); close=float(b.get("c") or 0); vol=float(b.get("v") or 0)
        if high<=0: continue
        high_pct=(high/prev-1)*100
        close_pct=(close/prev-1)*100 if close>0 else high_pct
        if max_pct is None or high_pct>max_pct:
            max_pct,max_ts=high_pct,b["t"]
        for x in thresholds:
            if first[str(x)] is None and high_pct>=x:
                first[str(x)]=b["t"]
        accel=None; vol_accel=None
        if prior_pct is not None and prior_ts:
            dt=(datetime.fromisoformat(b["t"].replace("Z","+00:00"))-datetime.fromisoformat(prior_ts.replace("Z","+00:00"))).total_seconds()/60
            if dt>0:
                accel=(close_pct-prior_pct)/dt
                if prior_vol is not None:
                    vol_accel=max(0.0,vol-prior_vol)/dt
        if close_pct<10:
            observations.append({"t":b["t"],"close_pct":close_pct,"accel_pp_min":accel,"volume":vol,"fresh_volume_per_min":vol_accel})
        prior_pct,prior_vol,prior_ts=close_pct,vol,b["t"]
    def lead(a,b):
        if not first[str(a)] or not first[str(b)]: return None
        return (datetime.fromisoformat(first[str(b)].replace("Z","+00:00"))-datetime.fromisoformat(first[str(a)].replace("Z","+00:00"))).total_seconds()/60
    return {
      **event,"max_intraday_pct":max_pct,"max_intraday_ts":max_ts,
      "first_cross":first,
      "lead_2_to_30_min":lead(2,30),"lead_5_to_30_min":lead(5,30),"lead_10_to_30_min":lead(10,30),
      "lead_2_to_50_min":lead(2,50),"lead_5_to_50_min":lead(5,50),"lead_10_to_50_min":lead(10,50),
      "pre10_observations":observations,
    }

def news_one(event,headers):
    # Look from previous calendar day 16:00 ET through the first +30 bar (or end of event day).
    d=datetime.fromisoformat(event["date"]).replace(tzinfo=ET)
    start=(d-timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0)
    end_ts=event.get("first_cross",{}).get("30")
    end=datetime.fromisoformat(end_ts.replace("Z","+00:00")).astimezone(ET) if end_ts else d.replace(hour=20)
    payload=request_json("/v1beta1/news",{
      "symbols":event["symbol"],"start":start.isoformat(),"end":end.isoformat(),
      "limit":50,"sort":"asc","include_content":"false"
    },headers)
    items=payload.get("news") or []
    cats=[]
    for n in items:
        text=((n.get("headline") or "")+" "+(n.get("summary") or "")).lower()
        for cat,words in CATALYST_RULES:
            if any(w in text for w in words):
                cats.append(cat)
    return {
      "news_count_pre30":len(items),
      "catalyst_categories":sorted(set(cats)),
      "headlines":[{"created_at":n.get("created_at"),"headline":n.get("headline")} for n in items[:8]]
    }

def med(vals):
    vals=sorted(v for v in vals if v is not None)
    if not vals:return None
    n=len(vals)
    return vals[n//2] if n%2 else (vals[n//2-1]+vals[n//2])/2

def pct(vals,q):
    vals=sorted(v for v in vals if v is not None)
    if not vals:return None
    return vals[min(len(vals)-1,max(0,round((len(vals)-1)*q)))]

def summarize(events):
    n=len(events)
    reached50=sum(1 for e in events if (e["max_intraday_pct"] or 0)>=50)
    news=sum(1 for e in events if e.get("news_count_pre30",0)>0)
    categories={}
    for e in events:
        for c in e.get("catalyst_categories",[]):
            categories[c]=categories.get(c,0)+1
    def availability(th):
        return sum(1 for e in events if e["first_cross"].get(str(th)) and e["first_cross"].get("30"))/n if n else None
    return {
      "sample_size":n,"reached_50_count":reached50,
      "pre30_news_available_count":news,"pre30_news_available_rate":news/n if n else None,
      "catalyst_category_counts":dict(sorted(categories.items(),key=lambda x:(-x[1],x[0]))),
      "had_2pct_before_30_rate":availability(2),
      "had_5pct_before_30_rate":availability(5),
      "had_10pct_before_30_rate":availability(10),
      "lead_2_to_30_median_min":med([e["lead_2_to_30_min"] for e in events]),
      "lead_5_to_30_median_min":med([e["lead_5_to_30_min"] for e in events]),
      "lead_10_to_30_median_min":med([e["lead_10_to_30_min"] for e in events]),
      "lead_5_to_30_p25_min":pct([e["lead_5_to_30_min"] for e in events],.25),
      "lead_5_to_30_p75_min":pct([e["lead_5_to_30_min"] for e in events],.75),
      "lead_10_to_30_p25_min":pct([e["lead_10_to_30_min"] for e in events],.25),
      "lead_10_to_30_p75_min":pct([e["lead_10_to_30_min"] for e in events],.75),
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--universe",default="config/universe.csv")
    p.add_argument("--out",default="research/300_winner_stress_test.json")
    p.add_argument("--count",type=int,default=300)
    p.add_argument("--lookback-days",type=int,default=240)
    p.add_argument("--feed",default="iex")
    p.add_argument("--workers",type=int,default=4)
    a=p.parse_args()
    key=os.environ["ALPACA_API_KEY"]; secret=os.environ["ALPACA_SECRET_KEY"]
    headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=a.lookback_days)
    symbols=load_universe(a.universe)
    daily=historical_daily(symbols,start.isoformat(),end.isoformat(),headers,a.feed)
    raw=candidate_events(daily)
    # Use most recent 300 unique symbol-session events.
    chosen=[]; seen=set()
    for e in raw:
        k=(e["symbol"],e["date"])
        if k not in seen:
            chosen.append(e);seen.add(k)
        if len(chosen)>=a.count: break
    reconstructed=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        fut={pool.submit(intraday_one,e,headers,a.feed):e for e in chosen}
        for f in as_completed(fut):
            reconstructed.append(f.result())
    reconstructed=[e for e in reconstructed if e["first_cross"].get("30")]
    reconstructed.sort(key=lambda e:(e["date"],e["symbol"]),reverse=True)
    with ThreadPoolExecutor(max_workers=max(1,min(3,a.workers))) as pool:
        fut={pool.submit(news_one,e,headers):i for i,e in enumerate(reconstructed)}
        for f in as_completed(fut):
            i=fut[f]
            try: reconstructed[i].update(f.result())
            except Exception as exc: reconstructed[i].update({"news_error":str(exc),"news_count_pre30":0,"catalyst_categories":[],"headlines":[]})
    payload={
      "status":"RESEARCH_ONLY","authoritative":False,
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "feed":a.feed,"lookback_days":a.lookback_days,
      "limitations":[
        "current-universe survivorship bias",
        "IEX is partial-market coverage",
        "historical float/market-cap state not reconstructed",
        "full cross-sectional live ranker is not replayed",
        "headline keyword catalyst classification is research-only"
      ],
      "summary":summarize(reconstructed[:a.count]),
      "events":reconstructed[:a.count]
    }
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload["summary"],sort_keys=True))
    if len(payload["events"])<a.count:
        raise SystemExit(f"only {len(payload['events'])} reconstructable winners; increase lookback")

if __name__=="__main__":
    main()
