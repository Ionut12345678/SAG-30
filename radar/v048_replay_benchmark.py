import sqlite3,json,statistics
from collections import defaultdict
from datetime import datetime
db=sqlite3.connect('/tmp/radar.sqlite3')
R=db.execute("select session,symbol,retrieval_ts,change_pct,bar_high_pct,observed_volume,bid,ask,spread_pct,minute_bar_present,consecutive_minute_bar from fast_path_events where change_pct is not null order by session,symbol,retrieval_ts,id").fetchall()
G=defaultdict(list)
for r in R:G[(r[0],r[1])].append(r)
D=lambda x:datetime.fromisoformat(x.replace('Z','+00:00'))
C=[]
for (se,sy),rr in G.items():
 pk=max(float(x[4] if x[4] is not None else x[3]) for x in rr)
 if pk<5:continue
 vs=[];st=0;dec=0;sg=None;mh=-999
 for i,x in enumerate(rr):
  p=float(x[3]);h=float(x[4] if x[4] is not None else p);v=x[5];early=mh<10 and h<10
  if x[9] and v is not None:
   pos=bool(x[10] and early and 0<p<10 and i and p>float(rr[i-1][3]) and float(v)>0);st=st+1 if pos else 0
   base=not dec and early and 0<p<10 and st>=2
   med=statistics.median(vs[-20:]) if vs else 0;ra=float(v)/med if med>0 else None
   if base:
    dec=1
    if ra is not None and ra>=1.5:sg=(i,x[2],p,h,float(v),ra,x[6],x[7],x[8])
   if float(v)>0:vs.append(float(v))
  mh=max(mh,h)
  if dec:break
 s1=False;s2=False
 if sg:
  i,t,e,hh,sv,ra,bi,ak,sp=sg;s1=bool(1.5<=e<=8 and ra>=2 and bi is not None and ak is not None and sp is not None and sp<=2)
  if s1:
   F=[]
   for x in rr[i+1:]:
    m=(D(x[2])-D(t)).total_seconds()/60
    if m>10:break
    if m>0 and x[9]:F.append((m,float(x[3]),float(x[4] if x[4] is not None else x[3]),float(x[5] or 0)))
   if F and max(z[0] for z in F)>=2:
    ch=[z[1] for z in F];hi=[z[2] for z in F];vv=[z[3] for z in F if z[3]>0];mx=max([e]+ch);ps=0;pr=e
    for z in ch:ps+=z>pr;pr=z
    vr=statistics.median(vv)/sv if sv and vv else None;ad=mx-e;gb=(mx-ch[-1])/ad if ad>0 else 1
    s2=bool(max(hi)>hh and ad>=2 and ps>=2 and vr is not None and vr>=.5 and gb<=.4)
 early=[x for x in rr if x[9] and x[3] is not None and 0<float(x[3])<10]
 C.append(dict(session=se,symbol=sy,peak=round(pk,2),early_observable=len(early)>=3,early_bar_count=len(early),first_change=round(float(rr[0][3]),2),v047=bool(sg),stage1=s1,stage2=s2,entry=round(sg[2],2) if sg else None,activity=round(sg[5],2) if sg else None,spread=round(sg[8],2) if sg and sg[8] is not None else None))
def M(k):
 w=[x for x in C if x['peak']>=30];h=[x for x in C if x['peak']<30];w50=[x for x in w if x['peak']>=50];tp=sum(x[k] for x in w);fp=sum(x[k] for x in h);t50=sum(x[k] for x in w50)
 ew=[x for x in w if x['early_observable']]; ew50=[x for x in w50 if x['early_observable']]
 return dict(winners=len(w),winners50=len(w50),early_observable_winners=len(ew),early_observable_winners50=len(ew50),hard_negatives=len(h),winner_detected=tp,winner50_detected=t50,early_winner_detected=sum(x[k] for x in ew),early_winner50_detected=sum(x[k] for x in ew50),hard_negative_detected=fp,recall30=tp/len(w) if w else None,recall50=t50/len(w50) if w50 else None,eligible_recall30=sum(x[k] for x in ew)/len(ew) if ew else None,eligible_recall50=sum(x[k] for x in ew50)/len(ew50) if ew50 else None,fpr=fp/len(h) if h else None,precision=tp/(tp+fp) if tp+fp else None)
O=dict(status='DESCRIPTIVE_REPLAY_PROXY_NOT_OOS_NOT_BUY',cohort=dict(cases=len(C),sessions=sorted(set(x['session'] for x in C))),metrics={k:M(k) for k in ['v047','stage1','stage2']},winners=[x for x in C if x['peak']>=30],hard_negative_stage2=[x for x in C if x['peak']<30 and x['stage2']],winner_lost_stage1=[x for x in C if x['peak']>=30 and x['v047'] and not x['stage1']],winner_lost_stage2=[x for x in C if x['peak']>=30 and x['stage1'] and not x['stage2']],note='Frozen current v0.4.8 gates; retrieval-time replay proxy; no retuning or OOS credit.')
open('reports/v048_replay_benchmark.json','w').write(json.dumps(O,indent=2,sort_keys=True))
print(json.dumps(O['metrics'],sort_keys=True))
