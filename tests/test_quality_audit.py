import unittest
from datetime import datetime,timezone
from radar_quality_audit import audit
from radar_followup import merge_scan

T=datetime(2026,10,19,14,0,tzinfo=timezone.utc)
def payload(p):
 return {"data":{"rows":[{"symbol":"TEST","pctchange":f"{p}%","lastsale":"$2.00"}]}}
class QualityTests(unittest.TestCase):
 def test_fresh_record_is_unknown_not_loser(self):
  state,follow=merge_scan({},payload(7),T)
  result=audit(state,{"scan_status":"DISCOVERY_ONLY"},dict(follow,same_snapshot_as_discovery=True),T)
  self.assertEqual(result["tracked_candidates"],1)
  self.assertEqual(result["candidates_without_later_snapshot"],1)
  self.assertEqual(result["reported_milestones_cumulative"]["50"],0)
  self.assertEqual(result["valid_buy_signals"],0)
 def test_mismatched_input_flags_gap(self):
  s,f=merge_scan({},payload(7),T)
  result=audit(s,{"scan_status":"DISCOVERY_ONLY"},f,T)
  self.assertEqual(result["data_quality_status"],"DATA_GAP_OR_INCONSISTENT")
 def test_never_marks_verified_live(self):
  s,f=merge_scan({},payload(7),T)
  r=audit(s,{"scan_status":"DISCOVERY_ONLY"},dict(f,same_snapshot_as_discovery=True),T)
  self.assertFalse(r["quote_source_time_verified"])
  self.assertFalse(r["full_market_coverage_verified"])
if __name__=="__main__": unittest.main()
