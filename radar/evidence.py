"""Prospective evidence packet builder for SAG-30 v0.3.3 FROZEN.

Collects only directly observable facts from stored market snapshots. Semantic gates
left undefined by the frozen prose remain unresolved rather than being manufactured.
"""
import json

def observed_packet(db, observation_id, external=None):
    row=db.execute("""SELECT symbol,retrieval_ts,source_ts,quality,price,change_pct,payload
                      FROM observations WHERE id=?""",(observation_id,)).fetchone()
    if not row:
        raise ValueError('Unknown observation')
    symbol,retrieved,source,quality,price,pct,payload=row
    prior=db.execute("""SELECT id,retrieval_ts,source_ts,price,change_pct,payload
                        FROM observations WHERE symbol=? AND id<? AND quality='OK'
                        ORDER BY id DESC LIMIT 3""",(symbol,observation_id)).fetchall()
    snapshot=json.loads(payload)
    def slim(r):
        p=json.loads(r[5])
        return {'observation_id':r[0],'retrieval_ts':r[1],'source_ts':r[2],
                'price':r[3],'change_pct':r[4],
                'minute_bar':p.get('minuteBar'),'daily_bar':p.get('dailyBar')}
    packet={
      'symbol':symbol,'source_ts':source,'retrieval_ts':retrieved,'quality':quality,
      'price':price,'change_pct':pct,
      'provenance':{'provider':'Alpaca','snapshot_source_ts':source,'observation_id':observation_id},
      'latest':{'minute_bar':snapshot.get('minuteBar'),'daily_bar':snapshot.get('dailyBar'),'prev_daily_bar':snapshot.get('prevDailyBar')},
      'prior_observations':[slim(r) for r in reversed(prior)],
      'rvol':None,
      'valid_activity_baseline':{'value':False,'provenance':'UNRESOLVED: frozen spec defines no baseline construction'},
      'lane_classification':{'value':False,'provenance':'UNRESOLVED: no sourced lane adjudication'},
      'price_conversion':{'value':False,'provenance':'UNRESOLVED: frozen spec forbids inventing a numeric conversion threshold'},
      'acceptance_reclaim':{'value':False,'provenance':'UNRESOLVED: requires sourced chronological adjudication'},
      'acceptance_still_valid':{'value':False,'provenance':'UNRESOLVED: requires sourced chronological adjudication'},
      'no_absorption':{'value':False,'provenance':'UNRESOLVED: minimal progress is not numerically defined'},
      'failed_acceptance':{'value':False,'provenance':'UNRESOLVED: material giveback is not numerically defined'},
    }
    external=external or {}
    if external.get('symbol') == symbol and external.get('source_ts') == source:
        for key,value in external.items():
            if key not in ('symbol','source_ts','retrieval_ts','quality','price','change_pct','provenance','latest','prior_observations'):
                packet[key]=value
    return packet
