"""Yahoo feed validation regressions without optional third-party dependencies."""
import datetime as dt
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from radar.pre50_fetch import fetch


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows
        end = dt.datetime(2026, 8, 4)
        dates = []
        day = end
        while len(dates) < len(rows):
            if day.weekday() < 5:
                dates.append(day)
            day -= dt.timedelta(days=1)
        self.index = list(reversed(dates))
        self.loc = self

    def __getitem__(self, mask):
        selected = FakeFrame([])
        selected.rows = [row for row, keep in zip(self.rows, mask) if keep]
        selected.index = [day for day, keep in zip(self.index, mask) if keep]
        return selected

    def __len__(self):
        return len(self.rows)

    def iterrows(self):
        for day, row in zip(self.index, self.rows):
            yield day, row


def run_fetch(rows, directory):
    fake_ticker = types.SimpleNamespace(history=lambda **kwargs: FakeFrame(rows))
    fake_yf = types.SimpleNamespace(Ticker=lambda symbol: fake_ticker)
    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        return fetch(["SOFI"], directory, now=dt.datetime(2026, 8, 5, 12, tzinfo=dt.timezone.utc))


class TestPre50FetchValidation(unittest.TestCase):
    def test_rejects_invalid_prices_and_cleans_stale_csv(self):
        good = {"Open": 9, "High": 10, "Low": 8, "Close": 9.5, "Volume": 100}
        invalid_bars = [
            {"Open": 0, "High": 10, "Low": 0, "Close": 9, "Volume": 100},
            {"Open": 9, "High": 10, "Low": 0, "Close": 9.5, "Volume": 100},
            {"Open": 9, "High": 10, "Low": 8, "Close": float("nan"), "Volume": 100},
            {"Open": 9, "High": 10, "Low": 8, "Close": float("inf"), "Volume": 100},
            {"Open": 9, "High": 10, "Low": 8, "Close": 9.5, "Volume": -1},
            {"Open": 11, "High": 10, "Low": 8, "Close": 9.5, "Volume": 100},
        ]
        for invalid in invalid_bars:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                csv_path = Path(directory) / "SOFI.csv"
                csv_path.write_text("stale data")
                report = run_fetch([good.copy() for _ in range(41)] + [invalid], directory)
                self.assertEqual(report["fetched"], 0)
                self.assertIn("SOFI", report["missing"])
                self.assertFalse(csv_path.exists())

    def test_valid_bars_with_zero_volume_are_accepted(self):
        row = {"Open": 9, "High": 10, "Low": 8, "Close": 9.5, "Volume": 0}
        with tempfile.TemporaryDirectory() as directory:
            report = run_fetch([row.copy() for _ in range(42)], directory)
            self.assertEqual(report["fetched"], 1)
            self.assertEqual(report["missing"], {})
            self.assertTrue((Path(directory) / "SOFI.csv").exists())


if __name__ == "__main__":
    unittest.main()
