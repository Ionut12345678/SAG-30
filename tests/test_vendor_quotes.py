import unittest
from datetime import datetime,timezone,timedelta
from radar_vendor_quotes import reconcile
from radar_cross_source import run

N=datetime(2026,10,21,15,0,tzinfo=timezone.utc)
def quote(symbol,price,minutes=0,status="RECENT_VENDOR_TIMESTAMP_UNVERIFIED"):
    return {"symbol":symbol,"status":status,"observed_price":price,
            "source_ts_utc":(N+timedelta(minutes=minutes)).isoformat()}
class VendorLedgerTests(unittest.TestCase):
    def test_two_distinct_vendor_times_return_twentyfive_percent(self):
        s,r=reconcile({},{"results":[quote("AAA",10)]})
        self.assertEqual(r["new_baselines"],1)
        s,r=reconcile(s,{"results":[quote("AAA",12.5,30)]})
        self.assertEqual(r["new_comparisons"],1)
        self.assertEqual(r["outcomes"][0]["return_pct"],25)
        self.assertEqual(r["threshold_counts"]["20"],1)
        self.assertEqual(r["threshold_counts"]["30"],0)
        self.assertFalse(r["outcomes"][0]["exchange_verified"])
    def test_repeated_or_older_timestamp_never_counts(self):
        s,_=reconcile({},{"results":[quote("AAA",10)]})
        s,r=reconcile(s,{"results":[quote("AAA",20)]})
        self.assertEqual(r["repeats_skipped"],1)
        self.assertEqual(r["new_comparisons"],0)
        self.assertEqual(s["symbols"]["AAA"]["last_price"],10)
    def test_stale_quote_cannot_open_baseline(self):
        s,r=reconcile({},{"results":[quote("AAA",10,status="STALE_TIMESTAMP")]})
        self.assertEqual(r["new_baselines"],0)
        self.assertEqual(r["stale_skipped"],1)
    def test_existing_tracker_prioritized_and_deduplicated(self):
        d={"candidates":[{"symbol":"AAA"},{"symbol":"BBB"}]}
        fetch=lambda sym:{"chart":{"result":[{"meta":{"regularMarketPrice":10.0,
          "chartPreviousClose":9.0,"regularMarketTime":int(N.timestamp())}}]}}
        r=run(d,N,fetch,tracked={"symbols":{"BBB":{"first_price":9}}})
        self.assertEqual(r["requested"],2)
        self.assertEqual([x["symbol"] for x in r["results"]],["BBB","AAA"])
if __name__=="__main__":unittest.main()
