import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radar.pre50_fetch import fetch


class TestPre50FetchValidation(unittest.TestCase):
    def test_rejects_zero_prices_and_does_not_leave_csv(self):
        import pandas as pd
        for invalid in (
            {"Open": 0, "High": 10, "Low": 0, "Close": 9, "Volume": 100},
            {"Open": 9, "High": 10, "Low": 0, "Close": 9.5, "Volume": 100},
            {"Open": 9, "High": 10, "Low": 8, "Close": float("nan"), "Volume": 100},
        ):
            rows = [{"Open": 9, "High": 10, "Low": 8, "Close": 9.5, "Volume": 100}] * 42
            rows[-1] = invalid
            frame = pd.DataFrame(rows, index=pd.date_range("2026-08-01", periods=42))
            with tempfile.TemporaryDirectory() as directory:
                with patch("yfinance.Ticker") as ticker:
                    ticker.return_value.history.return_value = frame
                    report = fetch(["SOFI"], directory)
                self.assertEqual(report["fetched"], 0)
                self.assertIn("SOFI", report["missing"])
                self.assertFalse((Path(directory) / "SOFI.csv").exists())

    def test_valid_bars_with_zero_volume_are_accepted(self):
        import pandas as pd
        rows = [{"Open": 9, "High": 10, "Low": 8, "Close": 9.5, "Volume": 0}] * 42
        frame = pd.DataFrame(rows, index=pd.date_range("2026-08-01", periods=42))
        with tempfile.TemporaryDirectory() as directory:
            with patch("yfinance.Ticker") as ticker:
                ticker.return_value.history.return_value = frame
                report = fetch(["SOFI"], directory)
            self.assertEqual(report["fetched"], 1)
            self.assertTrue((Path(directory) / "SOFI.csv").exists())


if __name__ == "__main__":
    unittest.main()
