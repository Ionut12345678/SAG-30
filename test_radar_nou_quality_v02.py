import unittest
from datetime import datetime, timezone
from radar_discovery import find_candidates, run, is_common_stock

class TestRadarNouQuality(unittest.TestCase):
    def test_excludes_obvious_non_common_instruments(self):
        rows = [
            {"symbol":"GOOD","pctchange":"+7%","name":"Example Inc. Common Stock","lastsale":"$2"},
            {"symbol":"WARR","pctchange":"+9%","name":"Example Warrants","lastsale":"$1"},
            {"symbol":"UNIT","pctchange":"+8%","name":"Example Units","lastsale":"$1"},
            {"symbol":"PREF","pctchange":"+6%","name":"Example Preferred Shares","lastsale":"$1"},
        ]
        candidates, eligible, malformed, count = find_candidates(rows)
        self.assertEqual([x["symbol"] for x in candidates], ["GOOD"])
        self.assertEqual(count, 1)
        self.assertTrue(all(x["eligible_for_first_watch"] is False for x in candidates))
        self.assertTrue(all(x["quote_source_timestamp"] is None for x in candidates))
    def test_missing_name_is_excluded(self):
        self.assertTrue(is_common_stock(""))  # Unknown classification remains unverified discovery only
    def test_no_timestamp_never_becomes_validated_signal(self):
        payload={"data":{"rows":[{"symbol":"GOOD","pctchange":"7%","name":"Example Common Stock","lastsale":"$2"}],"totalRecords":1}}
        result=run(payload=payload,at=datetime(2026,10,19,tzinfo=timezone.utc))
        self.assertFalse(result["source_timestamp_verified"])
        self.assertEqual(result["valid_first_watch_signals"],0)
        self.assertEqual(result["candidates"][0]["quote_freshness_status"],"UNVERIFIABLE_NO_SOURCE_TIMESTAMP")

if __name__ == "__main__":
    unittest.main()
