"""Radar100 paper-only scanner: append-only signals with deterministic review snapshots.
No broker connectivity, no BUY calls, no prediction revision. Source daily bars.
"""
import argparse,json,hashlib
from datetime import datetime,timezone
from pathlib import Path
from backtest import load
from filter_portfolio import enrich,select_signal

HORIZONS=(1,5,10,20)
STRATEGIES=("momentum","trend_volume")

def cycle(groups, ledger, run_id, scanned_at):
    state=json.loads(json.dumps(ledger))
    if state.get("version")!=1 or not isinstance(state.get("signals"),list):
        raise ValueError("Invalid persistent paper ledger")
    existing={x["id"] for x in state["signals"]}
    latest={}
    for name,bars in groups.items():
        if len(bars)<61:raise ValueError("Insufficient warmup: "+name)
        latest[name]=bars[-1]["date"].isoformat()
    # Strict common session, avoids inconsistent timestamps in universe.
    newest=min(latest.values())
    if len(set(latest.values()))!=1:
        raise ValueError("Stale/asynchronous price feeds: "+str(latest))
    new=[]
    # Only one new daily close can produce a new signal; hourly checks are idempotent.
    for symbol,bars in sorted(groups.items()):
        i=len(bars)-1
        if str(bars[i]["date"])!=newest:raise ValueError("Missing common session")
        for strategy in STRATEGIES:
            if select_signal(bars,i,strategy):
                ident=hashlib.sha256(f"{strategy}|{symbol}|{newest}".encode()).hexdigest()[:20]
                if ident not in existing:
                    record={"id":ident,"symbol":symbol,"strategy":strategy,
                      "signal_date":newest,"signal_close":bars[i]["close"],
                      "status":"pending_next_open","entry_date":None,"entry_open":None,
                      "outcomes":{}}
                    state["signals"].append(record);existing.add(ident);new.append(record)
    by_symbol={s:{b["date"].isoformat():idx for idx,b in enumerate(bars)}
               for s,bars in groups.items()}
    for signal in state["signals"]:
        sym=signal["symbol"]
        if sym not in groups:continue
        bars=groups[sym]; ix=by_symbol[sym].get(signal["signal_date"])
        if ix is None:continue
        # Entry is following bar open. Never claim entry at same day close.
        if signal["entry_date"] is None and ix+1<len(bars):
            signal["entry_date"]=str(bars[ix+1]["date"])
            signal["entry_open"]=bars[ix+1]["open"]
            signal["status"]="tracking"
        if signal["entry_date"] is None:continue
        entry_idx=by_symbol[sym].get(signal["entry_date"])
        for h in HORIZONS:
            key=str(h)
            if key in signal["outcomes"] or entry_idx+h>=len(bars):continue
            j=entry_idx+h
            gross=100*(bars[j]["close"]/signal["entry_open"]-1)
            net=100*(bars[j]["close"]*(1-.001)/(signal["entry_open"]*(1+.001))-1)
            signal["outcomes"][key]={"date":str(bars[j]["date"]),"gross_pct":round(gross,4),
                "net_10bps_each_side_pct":round(net,4)}
        if len(signal["outcomes"])==len(HORIZONS):signal["status"]="matured"
    state["last_scanned_date"]=newest
    state.setdefault("runs",[]).append({"run_id":str(run_id),"scanned_at_utc":scanned_at,
        "session":newest,"new_signals":len(new),"total_signals":len(state["signals"])})
    lines=["# Radar100 daily paper report","",
           f"Observation session: **{newest}**",
           f"New signals this cycle: **{len(new)}**",
           f"Signals tracked: **{len(state['signals'])}**","",
           "Strategy | Ticker | Signal date | Entry next open | 1d | 5d | 10d | 20d",
           "--- | --- | --- | --- | --- | --- | --- | ---"]
    for signal in state["signals"][-100:]:
        values=[f"{signal['outcomes'][str(h)]['net_10bps_each_side_pct']:+.2f}%" if str(h) in signal["outcomes"] else "—" for h in HORIZONS]
        lines.append(" | ".join([signal["strategy"],signal["symbol"],signal["signal_date"],
            str(signal["entry_open"]) if signal["entry_open"] is not None else "pending",*values]))
    lines+=["","*Paper research only; historical observations, no orders. Historical returns do not reflect FX, taxes, actual fills or intraday stop execution.*",""]
    return state,"\n".join(lines)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv");p.add_argument("--state",required=True)
    p.add_argument("--report",required=True);p.add_argument("--run-id",required=True)
    a=p.parse_args();groups=load(a.csv);enrich(a.csv,groups)
    state_path=Path(a.state)
    state=json.loads(state_path.read_text()) if state_path.exists() else {"version":1,"signals":[],"runs":[]}
    newer,report=cycle(groups,state,a.run_id,datetime.now(timezone.utc).isoformat())
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(newer,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    Path(a.report).write_text(report,encoding="utf-8")
    print(f"R100 session={newer['last_scanned_date']} new={newer['runs'][-1]['new_signals']} total={len(newer['signals'])}")
if __name__=="__main__":main()
