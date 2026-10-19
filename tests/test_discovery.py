import unittest
from radar_discovery import percent,get_rows,find_candidates,run

class TestDiscovery(unittest.TestCase):
 def test_percentage(self):
  self.assertEqual(percent("+7.23%"),7.23)
  self.assertEqual(percent("6.5%"),6.5)
  self.assertIsNone(percent("N/A"))
  self.assertIsNone(percent("nan"))
 def test_early_range(self):
  rows=[{"symbol":"AAA","pctchange":"+5.00%","lastsale":"$10"},
        {"symbol":"BBB","pctchange":"+7.21%","lastsale":"$2"},
        {"symbol":"CCC","pctchange":"+10.01%"},
        {"symbol":"DDD","pctchange":"-5.2%"},
        {"symbol":"EEE","pctchange":"10%"}]
  found,eligible,malformed,count=find_candidates(rows)
  self.assertEqual(count,3)
  self.assertEqual([x["symbol"] for x in found],["EEE","BBB","AAA"])
  self.assertTrue(all(x["eligible_for_first_watch"] is False for x in found))
  self.assertTrue(all(x["quote_source_timestamp"] is None for x in found))
 def test_missing_rows_fail_closed(self):
  with self.assertRaises(ValueError):get_rows({"data":{}})
 def test_report_no_signals_even_with_candidate(self):
  r=run(payload={"data":{"rows":[{"symbol":"ABC","pctchange":"7%"}],"totalRecords":10}})
  self.assertEqual(r["scan_status"],"DISCOVERY_ONLY")
  self.assertEqual(r["valid_first_watch_signals"],0)
  self.assertEqual(r["candidates_total"],1)
  self.assertTrue(r["partial_universe"])
 def test_empty_response_not_a_live_zero(self):
  r=run(payload={"data":{"rows":[]}})
  self.assertEqual(r["scan_status"],"EMPTY_SOURCE")
 def test_avoid_false_numeric(self):
  found,eligible,malformed,count=find_candidates([{"symbol":"$BAD","pctchange":"8%"},{"symbol":"OK","pctchange":"inf"}])
  self.assertEqual(count,0)

if __name__=="__main__": unittest.main()
