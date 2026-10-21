import unittest
from datetime import datetime, timezone
from radar_freshness_guard import validate, new_thresholds

NOW = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
def quote(ts="2026-10-19T18:29:30Z", pct=20):
    return dict(source_timestamp_verified_by_exchange=True, source_kind="trade",
                source_ts_utc=ts, pct_vs_previous_close=pct)

class GuardTests(unittest.TestCase):
    def test_stale(self):
        self.assertEqual(validate(quote("2026-10-16T20:00:00Z"), NOW)[1], "STALE_QUOTE")
    def test_screener_rejected(self):
        x=quote();x["source_kind"]="screener_snapshot"
        self.assertEqual(validate(x,NOW)[1],"SNAPSHOT_NOT_TRADE")
    def test_vendor_unverified(self):
        x=quote();x["source_timestamp_verified_by_exchange"]=False
        self.assertEqual(validate(x,NOW)[1],"UNVERIFIED_SOURCE")
    def test_replay(self):
        s={"OIO":{"baseline_verified":True,"baseline_source_ts_utc":"2026-10-19T18:20:00Z","last_accepted_source_ts_utc":"2026-10-19T18:29:30Z"}}
        self.assertEqual(new_thresholds(s,"OIO",quote(),NOW)[1],"REPLAYED_OR_OUT_OF_ORDER")
    def test_threshold_once(self):
        s={"OIO":{"baseline_verified":True,"baseline_source_ts_utc":"2026-10-19T18:20:00Z"}}
        self.assertEqual(new_thresholds(s,"OIO",quote(),NOW)[0],[15,20])
        self.assertEqual(new_thresholds(s,"OIO",quote("2026-10-19T18:29:50Z"),NOW)[0],[])
    def test_unverified_baseline(self):
        self.assertEqual(new_thresholds({"OIO":{}}, "OIO", quote(), NOW)[1],"UNVERIFIED_BASELINE")
if __name__ == "__main__":
    unittest.main()
