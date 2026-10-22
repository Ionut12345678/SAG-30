"""Read-only quality/coverage audit. NEVER asserts live price or BUY validation."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

def audit(state, discovery, followup, at=None):
    at=at or datetime.now(timezone.utc)
    session=at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    sessions=state.get("sessions",{}) if isinstance(state,dict) else {}
    ledger=sessions.get(session,{}) if isinstance(sessions,dict) else {}
    if not isinstance(ledger,dict):ledger={}
    tracked=list(ledger.values())
    n_followed=sum(int(x.get("followup_count") or 0)>0 for x in tracked if isinstance(x,dict))
    milestones={str(k):sum(k in (x.get("milestones_reported") or []) for x in tracked if isinstance(x,dict))
                for k in (15,20,30,50)}
    gaps=[]
    for x in tracked:
        if not isinstance(x,dict):continue
        first=x.get("first_seen_utc")
        last=x.get("last_seen_utc")
        if not first or not last:continue
        try:
            elapsed=(datetime.fromisoformat(last)-datetime.fromisoformat(first)).total_seconds()
            if elapsed<0:gaps.append("NEGATIVE_FOLLOWUP_INTERVAL")
        except (TypeError,ValueError):gaps.append("MALFORMED_TIME")
    ok=bool(discovery.get("scan_status")=="DISCOVERY_ONLY" and
      followup.get("status")=="UNVERIFIED_SCREENING_OBSERVED" and
      followup.get("same_snapshot_as_discovery") is True)
    return {
       "session":session,"mode":"UNVERIFIED_SHADOW_RESEARCH","valid_buy_signals":0,
       "same_snapshot_as_discovery":bool(followup.get("same_snapshot_as_discovery")),
       "data_quality_status":"CONSISTENT_UNVERIFIED_SNAPSHOT" if ok else "DATA_GAP_OR_INCONSISTENT",
       "tracked_candidates":len(ledger),"candidates_with_later_snapshot":n_followed,
       "candidates_without_later_snapshot":len(ledger)-n_followed,
       "unverified_reported_milestones_cumulative":milestones,
       "prospectively_validated_milestones":{"15":0,"20":0,"30":0,"50":0},
       "seconds_since_previous_success":followup.get("seconds_since_previous_success"),
       "hourly_cadence_met":followup.get("hourly_cadence_met",False),
       "missed_hourly_intervals":followup.get("missed_hourly_intervals"),
       "quote_source_time_verified":False,"full_market_coverage_verified":False,
       "source_quality_issues":gaps,
       "note":"Unverified milestone counts do not belong in the 30-day validated outcome. Reported changes are snapshots without verified exchange quote times. Milestones are NOT verified live opportunities."
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",default="candidate-state.json")
    p.add_argument("--discovery",default="radar-discovery.json")
    p.add_argument("--followup",default="candidate-followup.json")
    p.add_argument("--out",default="radar-quality.json")
    a=p.parse_args()
    def read(path):
        try:return json.loads(Path(path).read_text(encoding="utf-8"))
        except (ValueError,OSError):return {}
    res=audit(read(a.state),read(a.discovery),read(a.followup))
    Path(a.out).write_text(json.dumps(res,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:res[k] for k in ("data_quality_status","tracked_candidates","candidates_with_later_snapshot","reported_milestones_cumulative")}))
if __name__=="__main__":main()
