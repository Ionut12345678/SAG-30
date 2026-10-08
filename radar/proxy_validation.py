"""Conservative time-ordered SHADOW proxy validation. Never a BUY gate."""
from collections import Counter
from math import sqrt

def wilson(successes, total, z=1.96):
    if total<=0:
        return None
    p=successes/total
    denom=1+z*z/total
    center=(p+z*z/(2*total))/denom
    half=z*sqrt((p*(1-p)+z*z/(4*total))/total)/denom
    return {"low":max(0.0,center-half),"high":min(1.0,center+half)}

def validation(forward, min_per_group=30, min_sessions=5):
    """Split by session, never by individual observation (avoids same-day leakage).

    Only proxy>=3x and valid below-3x are comparable; missing-history
    candidates remain reported but do not contaminate either group.
    """
    cases=[r for r in forward.get("cases",[]) if r.get("status")=="FINALIZED"
           and r.get("cohort") in ("PROXY_3X","PROXY_BELOW_3X")]
    days=sorted({r["session"] for r in cases})
    if len(days)<2:
        return {"status":"INSUFFICIENT_SESSIONS","finalized_cases":len(cases),
                "sessions":len(days),"not_buy":True}
    boundary=max(1,int(len(days)*0.75))
    if boundary>=len(days):
        boundary=len(days)-1
    train_days=set(days[:boundary])
    result={"status":"DIAGNOSTIC_ONLY","not_buy":True,
            "split":"first 75% of session dates vs last 25%, chronological",
            "train_sessions":len(train_days),"validation_sessions":len(days)-len(train_days),
            "train":{},"validation":{},
            "note":"No parameter fitting, trading simulation, slippage or causal inference. Same-clock IEX baseline coverage and deep-selected sampling can bias both groups. Missing-history cases excluded from ratio comparison."}
    for name,subset in (("train",[r for r in cases if r["session"] in train_days]),
                        ("validation",[r for r in cases if r["session"] not in train_days])):
        by=Counter((r["cohort"],bool(r.get("first_observed_30_after_ts"))) for r in subset)
        per={}
        for cohort in ("PROXY_3X","PROXY_BELOW_3X"):
            n=sum(by[(cohort,x)] for x in (False,True))
            hits=by[(cohort,True)]
            per[cohort]={"n":n,"observed_30":hits,"rate":hits/n if n else None,
                         "wilson_95":wilson(hits,n)}
        result[name]=per
    val=result["validation"]
    hi=val["PROXY_3X"];lo=val["PROXY_BELOW_3X"]
    if len(days)-len(train_days)<min_sessions or min(hi["n"],lo["n"])<min_per_group:
        result["status"]="INSUFFICIENT_VALIDATION_SAMPLE"
        result["required_min_validation_sessions"]=min_sessions
        result["required_min_per_group"]=min_per_group
    elif hi["wilson_95"]["low"]>lo["wilson_95"]["high"]:
        result["status"]="VALIDATION_ASSOCIATION_DETECTED_NOT_BUY"
    else:
        result["status"]="NO_ROBUST_VALIDATION_SEPARATION"
    return result
