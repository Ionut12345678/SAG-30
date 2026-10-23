#!/usr/bin/env python3
"""Historical SQLite checkpoint audit. Read-only. Fail closed on corrupt or absent data."""
import argparse, gzip, hashlib, json, sqlite3, tempfile
from pathlib import Path

def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def audit(root):
    checkpoint=json.loads((root/"checkpoint.json").read_text())
    parts=[root/p["name"] for p in checkpoint["parts"]]
    for path,meta in zip(parts,checkpoint["parts"]):
        if not path.is_file():raise RuntimeError("MISSING_PART: "+path.name)
        if path.stat().st_size!=meta["bytes"] or digest(path)!=meta["sha256"]:
            raise RuntimeError("PART_HASH_MISMATCH: "+path.name)
    with tempfile.TemporaryDirectory() as tmp:
        packed=Path(tmp)/"radar.sqlite3.gz"
        with packed.open("wb") as target:
            for part in parts:
                with part.open("rb") as source:
                    for block in iter(lambda:source.read(4*1024*1024),b""):target.write(block)
        if packed.stat().st_size!=checkpoint["compressed_bytes"] or digest(packed)!=checkpoint["compressed_sha256"]:
            raise RuntimeError("COMPRESSED_HASH_MISMATCH")
        database=Path(tmp)/"radar.sqlite3"
        with gzip.open(packed,"rb") as source,database.open("wb") as dest:
            for block in iter(lambda:source.read(4*1024*1024),b""):dest.write(block)
        if database.stat().st_size!=checkpoint["database_bytes"] or digest(database)!=checkpoint["database_sha256"]:
            raise RuntimeError("DATABASE_HASH_MISMATCH")
        uri="file:"+str(database)+"?mode=ro"
        con=sqlite3.connect(uri,uri=True)
        try:
            integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
            names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts={}
            for name in checkpoint["table_counts"]:
                if name not in names:raise RuntimeError("MISSING_TABLE: "+name)
                counts[name]=con.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]
            mismatches={k:{"checkpoint":v,"actual":counts[k]} for k,v in checkpoint["table_counts"].items() if counts[k]!=v}
            report={"checkpoint_created_ts":checkpoint["created_ts"],"sqlite_integrity":integrity,
                    "database_sha256_verified":True,"checked_tables":len(counts),
                    "counts":counts,"count_mismatches":mismatches,
                    "experiment_21oct_to_20nov_included":False,"mode":"READ_ONLY_HISTORICAL_AUDIT"}
            # Record only schema metadata, never raw quotes or private observations.
            focus=("scout_history","scout_promotions","multi_engine_scores","observations","evaluations","candidate_v034_events","early_paper_follow_v12")
            schema={}
            for table in focus:
                if table in names:
                    schema[table]=[{"name":row[1],"type":row[2]} for row in con.execute('PRAGMA table_info("'+table+'")')]
            report["research_schema"]=schema
            report["research_note"]="Schema discovery only; no outcome-rate claim, no look-ahead or 30-day experiment mixing."
            # Historical funnel: earliest SCOUT observation inside +3..+10 for each
            # symbol-session, with strictly later promotion evidence only.
            # No future-price outcomes, no performance or BUY interpretation.
            early={}
            session_counts={}
            for session,symbol,ts,pct,selected in con.execute(
                "SELECT session,symbol,retrieval_ts,change_pct,selected "
                "FROM scout_history WHERE session IS NOT NULL AND symbol IS NOT NULL "
                "AND retrieval_ts IS NOT NULL AND change_pct BETWEEN 3 AND 10 "
                "ORDER BY session,symbol,retrieval_ts"):
                key=(session,symbol)
                if key not in early:
                    early[key]={"first_seen":ts,"pct":pct,"selected_at_first":bool(selected)}
                    session_counts[session]=session_counts.get(session,0)+1
            promotions={}
            for symbol,ts in con.execute(
                "SELECT symbol,scout_retrieval_ts FROM scout_promotions "
                "WHERE symbol IS NOT NULL AND scout_retrieval_ts IS NOT NULL "
                "ORDER BY scout_retrieval_ts"):
                promotions.setdefault(symbol,[]).append(ts)
            # Promotion table has no session: restrict to same UTC calendar date,
            # and only after the first timestamp. Conservative, may undercount.
            from bisect import bisect_right
            promoted=0
            initial_selected=0
            for (session,symbol),record in early.items():
                initial_selected+=int(record["selected_at_first"])
                future=promotions.get(symbol,[])
                idx=bisect_right(future,record["first_seen"])
                if idx<len(future) and future[idx][:10]==record["first_seen"][:10]:
                    promoted+=1
            report["historical_scout_funnel"]={
                "definition":"Earliest scout_history observation +3..+10 per symbol-session; strictly later scout_promotions timestamp, same UTC date",
                "candidate_symbol_sessions":len(early),
                "selected_at_first_seen":initial_selected,
                "later_promoted_same_utc_day":promoted,
                "sessions":dict(sorted(session_counts.items())),
                "first_seen_min":min((x["first_seen"] for x in early.values()),default=None),
                "first_seen_max":max((x["first_seen"] for x in early.values()),default=None),
                "limits":"Promotion is not validated opportunity, not subsequent price gain; session mapped conservatively via UTC date; no benchmark or causality claim.",
                "prospective_experiment_included":False}

            # Snapshot-only follow-up from actual stored observations.
            # Compare to preceding regular close via change_pct, NOT gain from entry.
            # Require strictly later retrieval AND source timestamps, same UTC date,
            # no duplicate source timestamps, and numeric non-null observed prices.
            from collections import defaultdict
            tracks=defaultdict(list)
            for symbol,rt,st,price,pct,quality in con.execute(
                "SELECT symbol,retrieval_ts,source_ts,price,change_pct,quality "
                "FROM observations WHERE symbol IS NOT NULL AND retrieval_ts IS NOT NULL "
                "AND source_ts IS NOT NULL AND price > 0 AND change_pct IS NOT NULL "
                "ORDER BY symbol,retrieval_ts"):
                tracks[symbol].append((rt,st,float(pct),str(quality or "")))
            groups={"selected_at_first":{"count":0,"with_future_sample":0,"hits":{str(t):0 for t in (15,20,30,50)}},
                    "not_selected_at_first":{"count":0,"with_future_sample":0,"hits":{str(t):0 for t in (15,20,30,50)}}}
            quality_counts=defaultdict(int)
            for (session,symbol),entry in early.items():
                group=groups["selected_at_first" if entry["selected_at_first"] else "not_selected_at_first"]
                group["count"]+=1
                first=entry["first_seen"]
                seen_source=set()
                highs=[]
                for rt,st,pct,quality in tracks.get(symbol,()):
                    if rt<=first or st<=first or rt[:10]!=first[:10] or st[:10]!=first[:10]:
                        continue
                    if st in seen_source:
                        continue
                    seen_source.add(st)
                    quality_counts[quality]+=1
                    highs.append(pct)
                if highs:
                    group["with_future_sample"]+=1
                    observed_max=max(highs)
                    for threshold in (15,20,30,50):
                        if observed_max>=threshold:group["hits"][str(threshold)]+=1
            report["historical_observed_thresholds"]={
                "groups":groups,"future_sample_quality_labels":dict(sorted(quality_counts.items())),
                "definition":"Observed subsequent change_pct against prior close, same UTC day; strictly later source AND retrieval times; deduplicate source timestamps",
                "not_entry_return":True,"historical_only":True,
                "limits":"Research diagnostic only. Source quality is reported, not independently validated. Sparse snapshots miss highs; session/date UTC approximation can exclude observations. No BUY and no prospective 21Oct-20Nov claims."}
            # Entry-price research: first observed eligible quote AT/AFTER SCOUT first_seen.
            # SCOUT table has no price column, so do NOT label the entry as the SCOUT price.
            entry_groups={}
            for label in ("selected_at_first","not_selected_at_first"):
                entry_groups[label]={"total":0,"with_entry_quote":0,"with_later_quote":0,
                    "positive_last":0,"negative_last":0,"flat_last":0,
                    "entry_return_hits":{str(t):0 for t in (5,10,15,20,30,50)},
                    "last_return_sum_pct":0.0,"best_return_sum_pct":0.0,
                    "worst_return_sum_pct":0.0}
            for (session,symbol),entry in early.items():
                g=entry_groups["selected_at_first" if entry["selected_at_first"] else "not_selected_at_first"]
                g["total"]+=1
                valid=[]
                seen=set()
                for rt,st,price,pct,quality in con.execute(
                    "SELECT retrieval_ts,source_ts,price,change_pct,quality FROM observations "
                    "WHERE symbol=? AND retrieval_ts>=? AND source_ts>=? "
                    "AND retrieval_ts IS NOT NULL AND source_ts IS NOT NULL AND price>0 "
                    "ORDER BY retrieval_ts,source_ts",(symbol,entry["first_seen"],entry["first_seen"])):
                    if rt[:10]!=entry["first_seen"][:10] or st[:10]!=entry["first_seen"][:10]:continue
                    if st in seen:continue
                    seen.add(st)
                    valid.append((rt,st,float(price)))
                if not valid:continue
                g["with_entry_quote"]+=1
                rt0,st0,p0=valid[0]
                future=[p for rt,st,p in valid[1:] if rt>rt0 and st>st0]
                if not future:continue
                g["with_later_quote"]+=1
                last=100*(future[-1]/p0-1)
                best=100*(max(future)/p0-1)
                worst=100*(min(future)/p0-1)
                g["last_return_sum_pct"]+=last
                g["best_return_sum_pct"]+=best
                g["worst_return_sum_pct"]+=worst
                g["positive_last"]+=int(last>0)
                g["negative_last"]+=int(last<0)
                g["flat_last"]+=int(last==0)
                for t in (5,10,15,20,30,50):
                    g["entry_return_hits"][str(t)]+=int(best>=t)
            for g in entry_groups.values():
                n=g["with_later_quote"]
                if n:
                    for raw,mean in (("last_return_sum_pct","mean_last_return_pct"),
                                      ("best_return_sum_pct","mean_best_observed_return_pct"),
                                      ("worst_return_sum_pct","mean_worst_observed_return_pct")):
                        g[mean]=round(g.pop(raw)/n,4)
                else:
                    for raw in ("last_return_sum_pct","best_return_sum_pct","worst_return_sum_pct"):g.pop(raw)
                    g.update(mean_last_return_pct=None,mean_best_observed_return_pct=None,mean_worst_observed_return_pct=None)
            report["historical_entry_quote_returns"]={
                "groups":entry_groups,
                "entry_definition":"First unique-price observation with retrieval_ts and source_ts at/after SCOUT first_seen, same UTC day",
                "returns_definition":"Later quote price / first eligible quote price - 1; not executable return or SCOUT entry price",
                "limitations":"SCOUT has no quoted entry price; many absent quotes. Excludes same-timestamp repeats and outside-date. Price source quality not independently certified. No transaction cost, bid-ask, delisting adjustment, or intrabar maximum. Historical only."}
            # Final historical verdict with transparent coverage, not a trading claim.
            cohort=report["historical_entry_quote_returns"]["groups"]
            verdict={}
            for label,g in cohort.items():
                n=g["with_later_quote"]
                verdict[label]={
                    "eligible":n,"initial":g["total"],
                    "coverage_pct":round(100*n/g["total"],2) if g["total"] else None,
                    "observed_hit20_pct":round(100*g["entry_return_hits"]["20"]/n,2) if n else None,
                    "observed_hit30_pct":round(100*g["entry_return_hits"]["30"]/n,2) if n else None,
                    "observed_hit50_pct":round(100*g["entry_return_hits"]["50"]/n,2) if n else None,
                    "mean_last_return_pct":g["mean_last_return_pct"]}
            a=verdict["selected_at_first"]
            b=verdict["not_selected_at_first"]
            report["historical_verdict"]={
                "cohorts":verdict,
                "mean_last_difference_percentage_points":
                    round(a["mean_last_return_pct"]-b["mean_last_return_pct"],4)
                    if a["mean_last_return_pct"] is not None and b["mean_last_return_pct"] is not None else None,
                "critical_limitations":[
                    "Selection groups have unequal observation coverage; missingness may bias comparison.",
                    "Historical only: no independent out-of-sample evaluation or causal evidence.",
                    "Prices are observed quote snapshots; not executable fills or realized PnL.",
                    "Same-UTC-day restriction; not a full multiday hold strategy.",
                    "No production/FROZEN changes; cannot infer results for 21 Oct–20 Nov experiment."],
                "decision":"RESEARCH_ONLY_NOT_READY_FOR_LIVE_BUY"}
            if integrity!="ok" or mismatches:raise RuntimeError("SQL_INTEGRITY_OR_COUNT_MISMATCH: "+json.dumps(report))
            return report
        finally:con.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",required=True)
    parser.add_argument("--output",default="historical-sqlite-integrity.json")
    args=parser.parse_args()
    report=audit(Path(args.root))
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"integrity":report["sqlite_integrity"],"tables":report["checked_tables"],"verified":True}))
if __name__=="__main__":main()
