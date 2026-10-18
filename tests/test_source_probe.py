import io, json, unittest
from unittest.mock import patch
from probe_public_sources import probe_one

class FakeResponse:
    def __init__(self,data): self.data=json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,_n): return self.data

class TestReadOnlyProbe(unittest.TestCase):
    def test_nasdaq_discovery_only(self):
        out=probe_one("nasdaq_screener","https://example.org",opener=lambda *a,**k: FakeResponse({"data":{"rows":[{"symbol":"TEST"}]}}))
        self.assertEqual(out["status"],"REACHABLE_UNTIMESTAMPED")
        self.assertFalse(out["prospective_signal_eligible"])
        self.assertFalse(out["source_timestamp_verified"])
    def test_empty_is_not_no_stocks(self):
        out=probe_one("nasdaq_screener","https://example.org",opener=lambda *a,**k: FakeResponse({"data":{"rows":[]}}))
        self.assertEqual(out["status"],"EMPTY")
    def test_stocks_price_never_signal(self):
        out=probe_one("stockprices_dev","https://example.org",opener=lambda *a,**k: FakeResponse({"Ticker":"AAPL","Price":100.0}))
        self.assertEqual(out["records"],1)
        self.assertFalse(out["prospective_signal_eligible"])
    def test_schema_failure(self):
        out=probe_one("nasdaq_screener","https://example.org",opener=lambda *a,**k: FakeResponse({}))
        self.assertEqual(out["status"],"SCHEMA_UNSUPPORTED")
    def test_invalid_payload(self):
        out=probe_one("stockprices_dev","https://example.org",opener=lambda *a,**k: FakeResponse({"a":1}))
        self.assertEqual(out["status"],"SCHEMA_UNSUPPORTED")
if __name__=="__main__": unittest.main()
