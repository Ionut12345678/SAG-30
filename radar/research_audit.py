"""Forward-only retention challenger and semantic blocker audit. Research only."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

def exists(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())

def retention_outcomes(db, now=None):
    """Count ALL retained symbol-sessions, including losers and pending sessions.

    Target outcomes must follow the FIRST actually recorded retention observation.
    Scout prices are outcome labels only; never reconstructed execution prices.
    """
    if not exists(db,"retention_shadow_observations"):
        return {"status":"NOT_STARTED","finalized":0,"pending":0}
    now=now or datetime.now(timezone.utc)
    et=now.astimezone(ZoneInfo("America/New_York"))
    today=et.date().isoformat()
    rows=db.execute(
        "SELECT session,symbol,MIN(observed_ts) FROM retention_shadow_observations "
        "WHERE status='SHADOW_FRESH_TRADE' AND observed_ts IS NOT NULL "
        "GROUP BY session,symbol ORDER BY session,symbol"
    ).fetchall()
    counts=Counter()
    cases=[]
    for session,symbol,first_ts in rows:
        closed=session<today or (session==today and et.hour>=20)
        future=db.execute(
            "SELECT retrieval_ts,change_pct FROM scout_history "
            "WHERE session=? AND symbol=? AND retrieval_ts>? "
            "ORDER BY retrieval_ts",(session,symbol,first_ts)
        ).fetchall() if exists(db,"scout_history") else []
        target30=next((t for t,p in future if p>=30),None)
        target50=next((t for t,p in future if p>=50),None)
        # Production coverage is observed deep data, not mere shortlist presence.
        # If deep was already present before challenger, challenger is not first.
        start_et=datetime.fromisoformat(session).replace(tzinfo=ZoneInfo("America/New_York"))
        utc_start=start_et.astimezone(timezone.utc).isoformat()
        utc_end=(start_et+timedelta(days=1)).astimezone(timezone.utc).isoformat()
        production=db.execute(
            "SELECT MIN(retrieval_ts) FROM observations WHERE symbol=? AND retrieval_ts>=? "
            "AND retrieval_ts<? AND quality='OK' AND "
            "EXISTS(SELECT 1 FROM scout_history h WHERE h.run_id=observations.run_id "
            "AND h.symbol=observations.symbol AND h.session=? AND h.selected=1)",
            (symbol,utc_start,utc_end,session)
        ).fetchone()[0] if exists(db,"observations") and exists(db,"scout_history") else None
        # Avoid treating UTC calendar day as ET session for production comparison.
        if production:
            try:
                if datetime.fromisoformat(production.replace('Z','+00:00')).astimezone(
                    ZoneInfo('America/New_York')).date().isoformat()!=session:
                    production=None
            except (TypeError,ValueError):
                production=None
        earlier_than_production=production is None or first_ts<production
        counts["cohort"]+=1
        counts["finalized" if closed else "pending"]+=1
        if closed:
            counts["observed_30_after"]+=int(target30 is not None)
            counts["observed_50_after"]+=int(target50 is not None)
            counts["earlier_than_production"]+=int(earlier_than_production)
            counts["early_and_30"]+=int(earlier_than_production and target30 is not None)
        cases.append({"session":session,"symbol":symbol,
            "status":"FINALIZED" if closed else "PENDING_SESSION_CLOSE",
            "first_retention_ts":first_ts,
            "first_production_deep_ts":production,
            "retention_before_production":earlier_than_production,
            "first_observed_30_after_ts":target30,
            "first_observed_50_after_ts":target50})
    finalized=counts["finalized"]
    return {"status":"PROSPECTIVE_SHADOW_NOT_BUY",
        "cohort":counts["cohort"],"finalized":finalized,"pending":counts["pending"],
        "observed_30_after":counts["observed_30_after"],
        "observed_50_after":counts["observed_50_after"],
        "earlier_than_production":counts["earlier_than_production"],
        "early_and_30":counts["early_and_30"],
        "observed_30_rate":counts["observed_30_after"]/finalized if finalized else None,
        "cases":cases[-150:],
        "note":"Denominator is unique actually observed retained symbol-sessions. Pending excluded from outcome rates. First production comparison uses available stored deep observations only. Not execution, BUY, or verified +30/+50 intracycle highs."}

def semantic_blockers(db, limit=500):
    """Count distinct factual blocker classes, never infer frozen gate validity."""
    if not exists(db,"observations"):
        return {"status":"NO_OBSERVATIONS"}
    obs=db.execute(
        "SELECT id,quality FROM observations ORDER BY id DESC LIMIT ?",(limit,)
    ).fetchall()
    if not obs:
        return {"status":"NO_OBSERVATIONS"}
    counts=Counter()
    quality=Counter()
    reasons=Counter()
    readiness=Counter()
    for oid,q in obs:
        quality[q]+=1
        if q!='OK':
            counts["data_quality_not_ok"]+=1
        if exists(db,"evidence"):
            row=db.execute("SELECT payload FROM evidence WHERE observation_id=?",(oid,)).fetchone()
        else:
            row=None
        if not row:
            counts["missing_evidence_packet"]+=1
        else:
            try:
                p=json.loads(row[0])
                baseline=p.get("valid_activity_baseline") or {}
                if not isinstance(p.get("rvol"),(float,int)):
                    counts["rvol_not_numeric"]+=1
                if baseline.get("value") is not True:
                    counts["baseline_not_validated"]+=1
                if not baseline.get("provenance") or str(baseline.get("provenance")).startswith("UNRESOLVED"):
                    counts["baseline_provenance_unresolved"]+=1
                if (isinstance(p.get("rvol"),(float,int)) and
                    baseline.get("value") is True and baseline.get("provenance")):
                    counts["activity_confirmable"]+=1
            except (ValueError,TypeError):
                counts["invalid_evidence_json"]+=1
        shadow=(db.execute("SELECT payload FROM semantic_shadow WHERE observation_id=?",(oid,)).fetchone()
                if exists(db,"semantic_shadow") else None)
        if not shadow:
            counts["missing_semantic_shadow"]+=1
        else:
            try:
                p=json.loads(shadow[0])
                if int(p.get("same_clock_volume_sample_count") or 0)==0:
                    counts["no_same_clock_history"]+=1
                ratio=p.get("observed_same_clock_volume_ratio")
                samples=int(p.get("same_clock_volume_sample_count") or 0)
                if not isinstance(ratio,(float,int)):
                    counts["no_observed_volume_ratio"]+=1
                # Versioned research-only 5-session same-clock proxy. It is NOT
                # the undefined authoritative v0.3.3 activity baseline.
                if q!='OK':
                    readiness["SOURCE_NOT_OK"]+=1
                elif samples<5:
                    readiness["INSUFFICIENT_HISTORY_LT5"]+=1
                elif not isinstance(ratio,(float,int)) or not (0<=ratio<1e9):
                    readiness["RATIO_MISSING_OR_INVALID"]+=1
                elif ratio<3:
                    readiness["RATIO_BELOW_3X"]+=1
                else:
                    readiness["SHADOW_ACTIVITY_PROXY_3X"]+=1
            except (ValueError,TypeError):
                counts["invalid_shadow_json"]+=1
    return {"status":"RESEARCH_DIAGNOSTIC_NOT_GATE",
        "sampled_observations":len(obs),"quality":dict(quality),
        "blockers_nonexclusive":dict(sorted(counts.items())),
        "shadow_activity_proxy_5_sessions_3x":dict(sorted(readiness.items())),
        "note":"Last observations across sessions. The 5-session/3x proxy is research-only and not v0.3.3 RVOL. Missing baseline provenance is not fixed by this proxy."}

def semantic_proxy_forward_outcomes(db, now=None):
    """First qualifying deep observation per session/symbol; future scout outcomes only.

    SHADOW observational cohort, NOT an unbiased prospective trading backtest.
    Proxy class is frozen at first deep observation under +10%; future information
    is used only to label the outcome after that timestamp.
    """
    if not all(exists(db,t) for t in ("observations","semantic_shadow","scout_history")):
        return {"status":"NOT_STARTED","cohorts":{}}
    now=now or datetime.now(timezone.utc)
    et=now.astimezone(ZoneInfo("America/New_York"))
    today=et.date().isoformat()
    observations=db.execute(
        "SELECT o.symbol,o.retrieval_ts,o.source_ts,o.quality,o.change_pct,s.payload "
        "FROM observations o JOIN semantic_shadow s ON s.observation_id=o.id "
        "WHERE o.quality='OK' AND o.change_pct>=-10 AND o.change_pct<10 "
        "ORDER BY o.retrieval_ts,o.id"
    ).fetchall()
    first={}
    for symbol,ts,source,quality,pct,raw in observations:
        try:
            instant=datetime.fromisoformat(ts.replace('Z','+00:00'))
            if instant.tzinfo is None: continue
            session=instant.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            key=(session,symbol)
            if key in first: continue
            p=json.loads(raw)
            n=int(p.get("same_clock_volume_sample_count") or 0)
            ratio=p.get("observed_same_clock_volume_ratio")
            if n<5:
                label="INSUFFICIENT_HISTORY"
            elif not isinstance(ratio,(float,int)) or not (0<=ratio<1e9):
                label="RATIO_INVALID"
            elif ratio>=3:
                label="PROXY_3X"
            else:
                label="PROXY_BELOW_3X"
            first[key]=(ts,float(pct),label,n,ratio)
        except (ValueError,TypeError):
            continue
    totals=defaultdict(Counter)
    cases=[]
    for (session,symbol),(ts,pct,label,n,ratio) in sorted(first.items()):
        closed=session<today or (session==today and et.hour>=20)
        # Do not give early-detection credit to already-observed +30 runners.
        prior30=db.execute(
            "SELECT 1 FROM scout_history WHERE session=? AND symbol=? "
            "AND retrieval_ts<=? AND change_pct>=30 LIMIT 1",
            (session,symbol,ts)
        ).fetchone()
        if prior30:
            continue
        future=db.execute(
            "SELECT retrieval_ts,change_pct FROM scout_history WHERE session=? "
            "AND symbol=? AND retrieval_ts>? ORDER BY retrieval_ts",
            (session,symbol,ts)
        ).fetchall()
        first30=next((t for t,p in future if p>=30),None)
        first50=next((t for t,p in future if p>=50),None)
        bucket=totals[label]
        bucket["cohort"]+=1
        bucket["finalized" if closed else "pending"]+=1
        if closed:
            bucket["later_observed_30"]+=int(first30 is not None)
            bucket["later_observed_50"]+=int(first50 is not None)
        cases.append({"session":session,"symbol":symbol,"first_deep_ts":ts,
                      "first_deep_pct":pct,"baseline_samples":n,"ratio":ratio,
                      "cohort":label,"status":"FINALIZED" if closed else "PENDING",
                      "first_observed_30_after_ts":first30,
                      "first_observed_50_after_ts":first50})
    cohorts={}
    for label,b in sorted(totals.items()):
        f=b["finalized"]
        cohorts[label]={"total":b["cohort"],"finalized":f,"pending":b["pending"],
                        "later_observed_30":b["later_observed_30"],
                        "later_observed_50":b["later_observed_50"],
                        "observed_30_rate":b["later_observed_30"]/f if f else None,
                        "observed_50_rate":b["later_observed_50"]/f if f else None}
    return {"status":"OBSERVATIONAL_FORWARD_LABELS_SHADOW_NOT_BUY",
            "cohorts":cohorts,"cases":cases[-200:],
            "note":"First valid sub-10% deep observation defines proxy cohort. Later scout snapshots label +30/+50, never selection. Deep-observed cohort is selected, not randomized; provider coverage and session censoring bias results. No tradability or predictive edge is established."}
