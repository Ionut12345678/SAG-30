"""Tests for public sample adapter without network dependency."""
import unittest
from unittest.mock import patch
from research.radar_v2.public_data_adapter import fetch

class FakeResponse:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return b'{"chart":{"result":[{"timestamp":[1793016000],"indicators":{"quote":[{"open":[100],"high":[110],"low":[99],"close":[105],"volume":[1234]}]}}],"error":null}}'

class TestPublicAdapter(unittest.TestCase):
    @patch("urllib.request.urlopen", return_value=FakeResponse())
    def test_parse_ohlcv(self, mocked):
        rows=fetch("AAPL")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["close"],105)
        self.assertEqual(rows[0]["volume"],1234)
        self.assertEqual(rows[0]["provider"],"yahoo_chart_unofficial")

    def test_reject_unsupported_interval(self):
        with self.assertRaises(ValueError): fetch("AAPL",interval="2m")

    def test_reject_unsupported_range(self):
        with self.assertRaises(ValueError): fetch("AAPL",range_="10y")
