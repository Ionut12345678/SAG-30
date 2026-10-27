import unittest
from datetime import datetime, timezone, timedelta
from radar_followup import merge_scan, parse_price

A=datetime(2026,10,19,14,0,tzinfo=timezone.utc)
def payload(*entries):
    return {"data":{"rows":[{"symbol":s,"pctchange":f"{v}%","lastsale":"$10.00"} for s,v in entries],"totalRecords":len(entries)}}

class FollowupTests(unittest.TestCase):
    def test_identical_snapshots_do_not_create_followups(self):
        state,first=merge_scan({},payload(("AAA",7)),A)
        for minute in (5,30,60):
            state,report=merge_scan(state,payload(("AAA",7)),A+timedelta(minutes=minute))
            self.assertEqual(report["duplicates_skipped"],1)
            self.assertEqual(report["changed_unverified_followups"],0)
            self.assertEqual(state["sessions"]["2026-10-19"]["AAA"]["followup_count"],0)
            self.assertEqual(report["independent_timestamped_followups_verified"],0)
        state,changed=merge_scan(state,payload(("AAA",8)),A+timedelta(minutes=90))
        self.assertEqual(changed["changed_unverified_followups"],1)
        self.assertEqual(state["sessions"]["2026-10-19"]["AAA"]["followup_count"],1)

    def test_partial_source_change_does_not_count_unchanged_symbols(self):
        state,_=merge_scan({},payload(("AAA",7),("BBB",6)),A)
        state,result=merge_scan(state,payload(("AAA",7),("BBB",8)),A+timedelta(minutes=10))
        self.assertEqual(result["duplicates_skipped"],1)
        self.assertEqual(result["changed_unverified_followups"],1)
        self.assertEqual(state["sessions"]["2026-10-19"]["AAA"]["followup_count"],0)
        self.assertEqual(state["sessions"]["2026-10-19"]["BBB"]["followup_count"],1)

    def test_legacy_persisted_state_skips_unchanged_prices(self):
        state,_=merge_scan({},payload(("AAA",7)),A)
        entry=state["sessions"]["2026-10-19"]["AAA"]
        entry.pop("last_snapshot_pct")
        entry.pop("last_snapshot_price")
        state,result=merge_scan(state,payload(("AAA",7)),A+timedelta(minutes=5))
        self.assertEqual(result["duplicates_skipped"],1)
        self.assertEqual(state["sessions"]["2026-10-19"]["AAA"]["followup_count"],0)

    def test_first_seen_immutable_and_real_later_followup(self):
        state,r=merge_scan({},payload(("AAA",7.0)),A)
        first=state["sessions"]["2026-10-19"]["AAA"]["first_seen_utc"]
        state,r=merge_scan(state,payload(("AAA",18.1)),A+timedelta(minutes=30))
        x=state["sessions"]["2026-10-19"]["AAA"]
        self.assertEqual(first,x["first_seen_utc"])
        self.assertEqual(r["new_candidates"],0)
        self.assertEqual(x["milestones_reported"],[15])
        self.assertEqual(x["highest_later_reported_pct"],18.1)
        self.assertEqual(x["followup_count"],1)
        self.assertEqual(r["valid_first_watch_signals"],0)
    def test_multiple_later_thresholds_without_hindsight(self):
        s,_=merge_scan({},payload(("AAA",6)),A)
        s,r=merge_scan(s,payload(("AAA",52)),A+timedelta(minutes=30))
        self.assertEqual(r["new_reported_milestones"],4)
        s,r=merge_scan(s,payload(("AAA",45)),A+timedelta(minutes=60))
        self.assertEqual(r["new_reported_milestones"],0)
    def test_no_same_timestamp_followup(self):
        s,_=merge_scan({},payload(("AAA",7)),A)
        s,r=merge_scan(s,payload(("AAA",52)),A)
        self.assertEqual(s["sessions"]["2026-10-19"]["AAA"]["followup_count"],0)
        self.assertEqual(r["new_reported_milestones"],0)
    def test_missing_feed_preserves_state(self):
        s,_=merge_scan({},payload(("AAA",7)),A)
        old=s.copy()
        s,r=merge_scan(s,{},A+timedelta(minutes=30))
        self.assertEqual(r["status"],"SOURCE_SCHEMA_ERROR")
        self.assertEqual(s,old)
    def test_empty_feed_preserves_state(self):
        s,_=merge_scan({},payload(("AAA",7)),A)
        s,r=merge_scan(s,payload(),A+timedelta(minutes=30))
        self.assertEqual(r["status"],"EMPTY_SOURCE")
        self.assertEqual(len(s["sessions"]["2026-10-19"]),1)
    def test_late_first_not_backfilled(self):
        s,r=merge_scan({},payload(("AAA",52)),A)
        self.assertEqual(r["new_candidates"],0)
        s,r=merge_scan(s,payload(("AAA",7)),A+timedelta(minutes=30))
        self.assertEqual(r["new_candidates"],1)
    def test_readonly_and_unverified(self):
        s,r=merge_scan({},payload(("AAA",7)),A)
        self.assertFalse(r["quote_timestamp_verified"])
        self.assertFalse(r["buy_enabled"])
        self.assertEqual(r["valid_first_watch_signals"],0)
    def test_price_parsing(self):
        self.assertEqual(parse_price("$1,230.30"),1230.3)
        self.assertIsNone(parse_price("N/A"))
        self.assertIsNone(parse_price("0"))
    def test_session_is_eastern(self):
        s,r=merge_scan({},payload(("AAA",7)),datetime(2026,10,20,1,0,tzinfo=timezone.utc))
        self.assertEqual(r["session"],"2026-10-19")

if __name__=="__main__":unittest.main()
