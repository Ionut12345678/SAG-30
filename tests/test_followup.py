import unittest
from datetime import datetime, timezone, timedelta
from radar_followup import merge_scan, parse_price

A=datetime(2026,10,19,14,0,tzinfo=timezone.utc)
def payload(*entries):
    return {"data":{"rows":[{"symbol":s,"pctchange":f"{v}%","lastsale":"$10.00"} for s,v in entries],"totalRecords":len(entries)}}

class FollowupTests(unittest.TestCase):
    def test_first_seen_immutable_and_real_later_followup(self):
        state,r=merge_scan({},payload(("AAA",7.0)),A)
        first=state["sessions"]["2026-10-19"]["AAA"]["first_seen_utc"]
        state,r=merge_scan(state,payload(("AAA",18.1)),A+timedelta(minutes=30))
        x=state["sessions"]["2026-10-19"]["AAA"]
        self.assertEqual(first,x["first_seen_utc"])
        self.assertEqual(r["new_candidates"],0)
        self.assertEqual(x["milestones_reported"],[])
        self.assertEqual(x["milestone_quality"],"UNVERIFIED_SNAPSHOT_NO_ALERT")
        self.assertEqual(x["highest_later_reported_pct"],18.1)
        self.assertEqual(x["followup_count"],1)
        self.assertEqual(r["valid_first_watch_signals"],0)
    def test_multiple_later_thresholds_without_hindsight(self):
        s,_=merge_scan({},payload(("AAA",6)),A)
        s,r=merge_scan(s,payload(("AAA",52)),A+timedelta(minutes=30))
        self.assertEqual(r["new_reported_milestones"],0)
        self.assertEqual(s["sessions"]["2026-10-19"]["AAA"]["highest_later_reported_pct"],52)
        s,r=merge_scan(s,payload(("AAA",45)),A+timedelta(minutes=60))
        self.assertEqual(r["new_reported_milestones"],0)
    def test_return_is_from_first_observed_price_not_daily_pct(self):
        s,_=merge_scan({},payload(("AAA",7)),A)
        later={"data":{"rows":[{"symbol":"AAA","pctchange":"52%","lastsale":"$12.50"}],"totalRecords":1}}
        s,r=merge_scan(s,later,A+timedelta(minutes=30))
        self.assertEqual(r["return_from_first_observation"][0]["return_pct"],25.0)
        self.assertFalse(r["return_from_first_observation"][0]["tradable_entry_verified"])
        self.assertEqual(r["new_reported_milestones"],0)
    def test_cross_session_retains_original_baseline(self):
        s,_=merge_scan({},payload(("AAA",7)),A)
        from datetime import timedelta
        next_day=A+timedelta(days=1)
        later={"data":{"rows":[{"symbol":"AAA","pctchange":"6%","lastsale":"$12.50"}],"totalRecords":1}}
        s,report=merge_scan(s,later,next_day)
        self.assertEqual(report["new_candidates"],0)
        self.assertEqual(report["return_from_first_observation"][0]["return_pct"],25.0)
        self.assertEqual(len(s["sessions"]),2)
    def test_no_same_timestamp_followup(self):
        s,_=merge_scan({},payload(("AAA",7)),A)
        s,r=merge_scan(s,payload(("AAA",52)),A)
        self.assertEqual(s["sessions"]["2026-10-19"]["AAA"]["followup_count"],0)
        self.assertEqual(r["new_reported_milestones"],0)
    def test_identical_source_snapshot_is_not_followup(self):
        first=payload(("AAA",7))
        s,_=merge_scan({},first,A)
        before=s["sessions"]["2026-10-19"]["AAA"].copy()
        s,r=merge_scan(s,first,A+timedelta(minutes=30))
        self.assertEqual(r["status"],"DUPLICATE_SOURCE_SNAPSHOT")
        self.assertEqual(s["sessions"]["2026-10-19"]["AAA"],before)
        self.assertEqual(r["return_from_first_observation"],[])
    def test_changed_price_creates_unverified_comparison(self):
        s,_=merge_scan({},payload(("AAA",7)),A)
        changed={"data":{"rows":[{"symbol":"AAA","pctchange":"28%","lastsale":"$12.50"}],"totalRecords":1}}
        s,r=merge_scan(s,changed,A+timedelta(minutes=30))
        self.assertEqual(r["comparison_count"],1)
        self.assertEqual(r["unverified_return_threshold_counts"]["20"],1)
        self.assertEqual(r["unverified_return_threshold_counts"]["30"],0)
        self.assertEqual(r["valid_first_watch_signals"],0)
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
