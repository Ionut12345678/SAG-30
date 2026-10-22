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
        self.assertFalse(result["hourly_cadence_met"])
        self.assertEqual(state["last_successful_scan_utc"],START.isoformat())
    def test_five_minute_window(self):
        state,_=merge_scan({},feed(7),START)
        state,result=merge_scan(state,feed(8),START+timedelta(minutes=5))
        self.assertEqual(result["seconds_since_previous_success"],300)
        self.assertTrue(result["hourly_cadence_met"])
        self.assertEqual(result["missed_hourly_intervals"],0)
    def test_thirty_minute_delay_detected(self):
        state,_=merge_scan({},feed(7),START)
        state,result=merge_scan(state,feed(20),START+timedelta(minutes=30))
        self.assertEqual(result["seconds_since_previous_success"],1800)
        self.assertTrue(result["hourly_cadence_met"])
        self.assertEqual(result["missed_hourly_intervals"],0)
        quality=audit(state,{"scan_status":"DISCOVERY_ONLY"},dict(result,same_snapshot_as_discovery=True),START+timedelta(minutes=30))
        self.assertEqual(quality["seconds_since_previous_success"],1800)
        self.assertEqual(quality["missed_hourly_intervals"],0)
    def test_failed_source_does_not_reset_cadence(self):
        state,_=merge_scan({},feed(7),START)
        state,error=merge_scan(state,{"bad":True},START+timedelta(minutes=5))
        self.assertEqual(error["status"],"SOURCE_SCHEMA_ERROR")
        self.assertEqual(state["last_successful_scan_utc"],START.isoformat())
        state,result=merge_scan(state,feed(8),START+timedelta(minutes=10))
        self.assertEqual(result["seconds_since_previous_success"],600)
if __name__=="__main__":unittest.main()
