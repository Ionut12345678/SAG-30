"""Dependency-free regression coverage for the Yahoo validation gate."""
import math
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from radar.pre50_fetch import fetch


class FakeFrame:
    def __init__(self, bad=None):
        self.rows = []
        for i in range(42):
            row = {"Open": 9.0, "High": 10.0, "Low": 8.0,
                   "Close": 9.5, "Volume": 100.0}
            if i == 41 and bad:
                row.update(bad)
            self.rows.append(row)

    def __len__(self):
        return len(self.rows)

    def iterrows(self):
        start = datetime(2026, 8, 1)
        for i, row in enumerate(self.rows):
            yield start + timedelta(days=i), row


class Pre50FetchCoreTests(unittest.TestCase):
    def run_fetch(self, bad=None):
        feed = types.SimpleNamespace(
            Ticker=lambda symbol: types.SimpleNamespace(
                history=lambda **kwargs: FakeFrame(bad)))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(sys.modules, {"yfinance": feed}):
                result = fetch(["SOFI"], tmp)
            exists = (Path(tmp) / "SOFI.csv").exists()
        return result, exists

    def test_invalid_prices_and_volume_fail_closed(self):
        for row in (
            {"Open": 0.0},
            {"Low": 0.0},
            {"Close": float("nan")},
            {"High": float("inf")},
            {"Volume": -1.0},
            {"Low": 11.0},
            {"High": 8.0},
        ):
            with self.subTest(row=row):
                result, exists = self.run_fetch(row)
                self.assertEqual(result["fetched"], 0)
                self.assertIn("SOFI", result["missing"])
                self.assertFalse(exists)

    def test_zero_volume_is_valid(self):
        result, exists = self.run_fetch({"Volume": 0.0})
        self.assertEqual(result["fetched"], 1)
        self.assertTrue(exists)


if __name__ == "__main__":
    unittest.main()
