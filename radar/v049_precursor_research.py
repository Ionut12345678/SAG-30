"""v0.4.9 rolling precursor research replay. DEV ONLY / NOT BUY."""
import sqlite3,json,statistics
from collections import defaultdict
db=sqlite3.connect('/tmp/radar.sqlite3')
R=db.execute("select session,symbol,retrieval_ts,change_pct,bar_high_pct,observed_volume,bid,ask,spread_pct,minute_bar_present,consecutive_minute_bar from fast_path_events where change_pct is not null order by session,symbol,retrieval_ts,id").fetchall()
G=defaultdict(list)
for r in R:G[(r[0],r[1])].append(r)
def replay(rr,act=1.5,steps=2,spread=2.0,lo=1.0,hi=9.5,lookback=20):
    vols=[]; pos=0; prev=None
    for i,x in enumerate(rr):
        p=float(x[3]); h=float(x[4] if x[4] is not None else p); v=float(x[5] or 0)
        # stop permanently once observed high reaches 10: no post-explosion dip gets early credit
        if h>=10: break
        if not x[9] or v<=0:
            prev=p; pos=0; continue
        med=statistics.median(vols[-lookback:]) if vols else 0
        ratio=v/med if med>0 else None
        rising=prev is not None and p>prev
        pos=pos+1 if rising else 0
        bid,ask,sp=x[6],x[7],x[8]
        execok=bid is not None and ask is not None and sp is not None and float(sp)<=spread
        if lo<=p<=hi and pos>=steps and ratio is not None and ratio>=act and execok:
            return dict(hit=True,index=i,entry=p,activity=ratio,spread=float(sp),ts=x[2])
        vols.append(v);prev=p
    return dict(hit=False)
cases=[]
specs={
 "ROLL_A15_S2":dict(act=1.5,steps=2),
 "ROLL_A20_S2":dict(act=2.0,steps=2),
 "ROLL_A15_S1":dict(act=1.5,steps=1),
 "ROLL_A20_S1":dict(act=2.0,steps=1),
}
for (se,sy),rr in G.items():
    pk=max(float(x[4] if x[4] is not None else x[3]) for x in rr)
    if pk<5:continue
    row=dict(session=se,symbol=sy,peak=pk,first_change=float(rr[0][3]))
    for name,kw in specs.items():row[name]=replay(rr,**kw)
    cases.append(row)
def metrics(name):
    w=[x for x in cases if x['peak']>=30]; w50=[x for x in w if x['peak']>=50]; h=[x for x in cases if 5<=x['peak']<30]
    # routing-eligible means there was at least one pre-10 minute bar before first >=10
    def early(x):
        rr=G[(x['session'],x['symbol'])]
        for z in rr:
            hh=float(z[4] if z[4] is not None else z[3])
            if hh>=10:return False
            if z[9] and 0<float(z[3])<10:return True
        return False
    ew=[x for x in w if early(x)]; ew50=[x for x in w50 if early(x)]
    tp=sum(x[name]['hit'] for x in w); fp=sum(x[name]['hit'] for x in h)
    return dict(winners=len(w),winner50=len(w50),pre10_winners=len(ew),pre10_winner50=len(ew50),
      detected_winners=tp,detected_winner50=sum(x[name]['hit'] for x in w50),
      detected_pre10=sum(x[name]['hit'] for x in ew),detected_pre10_50=sum(x[name]['hit'] for x in ew50),
      hard_negatives=len(h),false_hits=fp,
      eligible_recall30=sum(x[name]['hit'] for x in ew)/len(ew) if ew else None,
      eligible_recall50=sum(x[name]['hit'] for x in ew50)/len(ew50) if ew50 else None,
      fpr=fp/len(h) if h else None,precision=tp/(tp+fp) if tp+fp else None)
O={"status":"V0.4.9_ROLLING_PRECURSOR_DEV_REPLAY_NOT_OOS_NOT_BUY","specs":specs,
   "metrics":{n:metrics(n) for n in specs},
   "winner_detail":[{"session":x["session"],"symbol":x["symbol"],"peak":round(x["peak"],2),"first_change":round(x["first_change"],2),**{n:x[n] for n in specs}} for x in cases if x["peak"]>=30],
   "note":"DEV replay only. Stops at first observed >=10 to prevent late/dip hindsight. No changes to v0.3.3/v0.4.7/v0.4.8."}
open('reports/v049_rolling_precursor_dev.json','w').write(json.dumps(O,indent=2,sort_keys=True))
print(json.dumps(O["metrics"],sort_keys=True))
