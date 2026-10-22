"""Offline regression checks: no network, no trading."""
import unittest
from datetime import datetime, timezone
from radar_discovery import find_candidates
from radar_followup import merge_scan
from radar_quality_audit import audit

def payload(changes):
    return {"data":{"rows":[{"symbol":s,"pctchange":str(p),"lastsale":"$10"} for s,p in changes.items()],"totalRecords":len(changes)}}

class ProspectiveShadowTests(unittest.TestCase):
    def test_three_to_ten_inclusive(self):
        found, *_ = find_candidates(payload({"AAA":3,"BBB":10,"CCC":2.99,"DDD":10.01})["data"]["rows"])
        self.assertEqual({x["symbol"] for x in found},{"AAA","BBB"})
        self.assertTrue(all(x["eligible_for_first_watch"] is False for x in found))
    def test_first_seen_never_backdated_or_immediate_win(self):
        t=datetime(2026,10,22,15,0,tzinfo=timezone.utc)
        state, report=merge_scan({"version":1,"sessions":{}},payload({"AAA":6}),t)
        entry=state["sessions"]["2026-10-22"]["AAA"]
        self.assertEqual(entry["first_seen_utc"],t.isoformat())
        self.assertEqual(entry["milestones_reported"],[])
        self.assertEqual(report["valid_first_watch_signals"],0)
        self.assertEqual(report["new_candidates"],1)
    def test_followup_is_unverified(self):
        first=datetime(2026,10,22,15,0,tzinfo=timezone.utc)
        state,_=merge_scan(None,payload({"AAA":5}),first)
        second=datetime(2026,10,22,15,30,tzinfo=timezone.utc)
        state,report=merge_scan(state,payload({"AAA":20}),second)
        self.assertEqual(report["new_unverified_reported_milestones"],2)
        self.assertEqual(report["valid_first_watch_signals"],0)
        self.assertTrue(report["hourly_cadence_met"])
        summary=audit(state,{"scan_status":"DISCOVERY_ONLY"},
                      {"status":"UNVERIFIED_SCREENING_OBSERVED","same_snapshot_as_discovery":True},second)
        self.assertEqual(summary["prospectively_validated_milestones"]["20"],0)
        self.assertEqual(summary["unverified_reported_milestones_cumulative"]["20"],1)

if __name__=="__main__":
    unittest.main()
