"""Independent public daily-stock archive sample; no winner-label sampling.

Select a fixed reproducible SHA256 sample from ALL CSV files in upstream
collected_stocks, including delisted symbols when included upstream. No
claims of complete point-in-time universe or intraday execution.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from radar_annual_research import analyze_symbol,summarize

UPSTREAM="8ccb831aca1cda6a5d01471f7968e11552d88007"
TREE=f"https://api.github.com/repos/willhjw/big_movers/git/trees/{UPSTREAM}?recursive=1"
RAW=f"https://raw.githubusercontent.com/willhjw/big_movers/{UPSTREAM}/"
MAX_SYMBOLS=24
def sample_paths(files,limit=MAX_SYMBOLS):
    available=sorted({x for x in files if isinstance(x,str) and
                      x.startswith("collected_stocks/") and x.endswith(".csv") and
                      "/" not in x[len("collected_stocks/"): ]})
    return sorted(available,key=lambda x:hashlib.sha256(("radar-nou-sampling-v1:"+x).encode()).hexdigest())[:limit]

def decode_daily_csv(text):
    reader=csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames or not {"DateTime","Open","High","Low","Close","Volume"}.issubset(reader.fieldnames):
        raise ValueError("bad OHLCV schema")
    out=[]
    for row in reader:
        try:
            day=row["DateTime"][:10]
            if len(day)!=10:continue
            o,h,l,c,v=[float(row[k]) for k in ("Open","High","Low","Close","Volume")]
            if not all(math.isfinite(x) for x in (o,h,l,c,v)) or not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):
                continue
            if out and day<=out[-1]["session"]:continue
            if not "2025-10-01"<=day<="2026-10-21":continue
            out.append({"session":day,"open":o,"high":h,"low":l,"close":c,"volume":v})
        except (ValueError,TypeError,KeyError):continue
    return out

def fetch(url,limit=3500000):
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"RadarNou-Research/1.0"})
    with urllib.request.urlopen(req,timeout=20) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError("oversized upstream archive")
    return data

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="independent-daily-sample.json")
    args=p.parse_args()
    items=[];errors=[];total_files=None;selected=[]
    try:
        tree=json.loads(fetch(TREE,limit=10000000))
        if tree.get("truncated"):raise ValueError("upstream file tree truncated")
        files=[x["path"] for x in tree.get("tree",[]) if x.get("type")=="blob"]
        total_files=len([x for x in files if x.startswith("collected_stocks/") and x.endswith(".csv")])
        selected=sample_paths(files)
        if not selected:raise ValueError("no historical CSV files")
        for path in selected:
            symbol=path.split("/")[-1][:-4]
            try:
                raw=fetch(RAW+urllib.parse.quote(path,safe="/"))
                bars=decode_daily_csv(raw.decode("utf-8-sig"))
                item=analyze_symbol(symbol,bars)
                # Corporate-action adjustments are unknown. Treat extreme
                # close-to-close jumps as potential split/corporate-action gaps.
                suspicious=any(
                    bars[i-1]["close"]>0 and
                    (bars[i]["close"]/bars[i-1]["close"]>4 or bars[i]["close"]/bars[i-1]["close"]<.25)
                    for i in range(1,len(bars)))
                if suspicious:
                    item={"symbol":symbol,"sessions":len(bars),"events":[],"eligible":False,
                          "excluded_reason":"POTENTIAL_UNADJUSTED_CORPORATE_ACTION"}
                items.append(item)
            except Exception as exc:
                items.append({"symbol":symbol,"sessions":0,"events":[],"eligible":False,
                              "excluded_reason":"FETCH_OR_PARSE_FAILED"})
                errors.append({"symbol":symbol,"error_type":type(exc).__name__})
    except Exception as exc:
        errors.append({"step":"upstream_tree","error_type":type(exc).__name__})
    summary=summarize(items)
    summary.update({"data_origin":f"https://github.com/willhjw/big_movers/tree/{UPSTREAM}/collected_stocks",
      "randomization":"fixed SHA256 of stock filename, independent of winner labels",
      "total_archive_files":total_files,"sampled_files":len(selected),
      "errors":errors,"upstream_is_not_point_in_time_universe":True,
      "corporate_actions_fully_validated":False,"survivorship_bias_eliminated":False,
      "intraday_fill_validated":False,"buy_enabled":False})
    Path(args.out).write_text(json.dumps({"summary":summary,"symbols":items},indent=2)+"\n")
    print(json.dumps({k:summary.get(k) for k in
       ("status","total_archive_files","sampled_files","symbols_eligible","events_total","errors")}))
if __name__=="__main__":main()
