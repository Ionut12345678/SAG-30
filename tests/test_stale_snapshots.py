import unittest
from datetime import datetime, timedelta, timezone
from radar_followup import merge_scan
from radar_quality_audit import audit

NOW=datetime(2026,10,19,14,0,tzinfo=timezone.utc)
def feed(percentage, price="10.00"):
    return {"data":{"rows":[{"symbol":"ABC","pctchange":f"{percentage}%","lastsale":f"${price}"}]}}

class ScreenerFreshnessTests(unittest.TestCase):
    def test_same_snapshot_does_not_create_fake_followups(self):
        s,r1=merge_scan({},feed(7),NOW)
        s,r2=merge_scan(s,feed(7),NOW+timedelta(minutes=30))
        self.assertEqual(r2["status"],"REPEATED_UNCHANGED_SOURCE")
        self.assertTrue(r2["duplicate_source_snapshot"])
        self.assertEqual(s["sessions"]["2026-10-19"]["ABC"]["followup_count"],0)
        self.assertIsNone(s["sessions"]["2026-10-19"]["ABC"]["highest_later_reported_pct"])
        self.assertEqual(r2["new_reported_milestones"],0)
        a=audit(s,{"scan_status":"DISCOVERY_ONLY"},r2,NOW+timedelta(minutes=30))
        self.assertEqual(a["data_quality_status"],"STALE_REPEAT_NO_NEW_QUOTES")
    def test_new_snapshot_allows_new_followup(self):
        s,r1=merge_scan({},feed(7),NOW)
        s,r2=merge_scan(s,feed(15),NOW+timedelta(minutes=5))
        self.assertEqual(r2["status"],"UNVERIFIED_SCREENING_OBSERVED")
        self.assertEqual(r2["new_reported_milestones"],1)
        self.assertEqual(s["sessions"]["2026-10-19"]["ABC"]["followup_count"],1)
    def test_source_error_preserves_fingerprint(self):
        s,_=merge_scan({},feed(7),NOW)
        hash_before=s["last_successful_screen_hash"]
        s,err=merge_scan(s,{},NOW+timedelta(minutes=5))
        self.assertEqual(err["status"],"SOURCE_SCHEMA_ERROR")
        self.assertEqual(s["last_successful_screen_hash"],hash_before)
        s,r=merge_scan(s,feed(7),NOW+timedelta(minutes=10))
        self.assertEqual(r["status"],"REPEATED_UNCHANGED_SOURCE")
    def test_same_percent_different_trade_price_is_new_capture(self):
        s,_=merge_scan({},feed(7,"10"),NOW)
        s,r=merge_scan(s,feed(7,"11"),NOW+timedelta(minutes=2))
        self.assertEqual(r["status"],"UNVERIFIED_SCREENING_OBSERVED")
if __name__=="__main__":unittest.main()
