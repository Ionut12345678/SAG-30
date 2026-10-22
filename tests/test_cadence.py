import unittest
from datetime import datetime, timedelta, timezone
from radar_followup import merge_scan
from radar_quality_audit import audit

START=datetime(2026,10,19,14,0,tzinfo=timezone.utc)
def feed(pct):
    return {"data":{"rows":[{"symbol":"EXAMPLE","pctchange":f"{pct}%","lastsale":"$10"}]}}

class CadenceAuditTests(unittest.TestCase):
    def test_first_observation_cadence_unknown(self):
        state, result=merge_scan({},feed(7),START)
        self.assertIsNone(result["seconds_since_previous_success"])
        self.assertFalse(result["five_minute_cadence_met"])
        self.assertEqual(state["last_successful_scan_utc"],START.isoformat())
    def test_five_minute_window(self):
        state,_=merge_scan({},feed(7),START)
        state,result=merge_scan(state,feed(8),START+timedelta(minutes=5))
        self.assertEqual(result["seconds_since_previous_success"],300)
        self.assertTrue(result["five_minute_cadence_met"])
        self.assertEqual(result["missed_five_minute_intervals"],0)
    def test_thirty_minute_delay_detected(self):
        state,_=merge_scan({},feed(7),START)
        state,result=merge_scan(state,feed(20),START+timedelta(minutes=30))
        self.assertEqual(result["seconds_since_previous_success"],1800)
        self.assertFalse(result["five_minute_cadence_met"])
        self.assertEqual(result["missed_five_minute_intervals"],5)
        quality=audit(state,{"scan_status":"DISCOVERY_ONLY"},dict(result,same_snapshot_as_discovery=True),START+timedelta(minutes=30))
        self.assertEqual(quality["seconds_since_previous_success"],1800)
        self.assertEqual(quality["missed_five_minute_intervals"],5)
    def test_failed_source_does_not_reset_cadence(self):
        state,_=merge_scan({},feed(7),START)
        state,error=merge_scan(state,{"bad":True},START+timedelta(minutes=5))
        self.assertEqual(error["status"],"SOURCE_SCHEMA_ERROR")
        self.assertEqual(state["last_successful_scan_utc"],START.isoformat())
        state,result=merge_scan(state,feed(8),START+timedelta(minutes=10))
        self.assertEqual(result["seconds_since_previous_success"],600)
class CrossSessionFollowupTests(unittest.TestCase):
    def test_previous_session_remains_observed_without_unverified_alert(self):
        start=datetime(2026,10,19,14,0,tzinfo=timezone.utc)
        state,_=merge_scan({},feed(7),start)
        following=start+timedelta(days=1)
        state,report=merge_scan(state,feed(30),following)
        old=state["sessions"]["2026-10-19"]["EXAMPLE"]
        self.assertEqual(report["older_session_symbols_observed"],1)
        self.assertEqual(old["last_observed_session"],"2026-10-20")
        self.assertEqual(old["last_reported_daily_pct"],30)
        self.assertIsNotNone(old["estimated_pct_vs_initial_prior_close"])
        self.assertEqual(old["cross_session_thresholds_confirmed"],[])
        self.assertEqual(report["older_session_thresholds_confirmed"],0)
        self.assertEqual(old["milestones_reported"],[])
        self.assertFalse(old["cross_session_quote_timestamp_verified"])
    def test_absent_prior_symbol_is_not_fake_updated(self):
        state,_=merge_scan({},feed(7),START)
        payload={"data":{"rows":[{"symbol":"OTHER","pctchange":"9%","lastsale":"$12"}]}}
        state,report=merge_scan(state,payload,START+timedelta(days=1))
        self.assertEqual(report["older_session_symbols_observed"],0)
        self.assertNotIn("last_seen_utc",state["sessions"]["2026-10-19"]["EXAMPLE"])
    def test_missing_price_remains_unverified(self):
        state,_=merge_scan({},feed(7),START)
        payload={"data":{"rows":[{"symbol":"EXAMPLE","pctchange":"50%","lastsale":"N/A"}]}}
        state,report=merge_scan(state,payload,START+timedelta(days=1))
        old=state["sessions"]["2026-10-19"]["EXAMPLE"]
        self.assertIsNone(old["estimated_pct_vs_initial_prior_close"])
        self.assertEqual(report["older_session_thresholds_confirmed"],0)

if __name__=="__main__":unittest.main()
