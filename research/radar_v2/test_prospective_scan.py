"""Prospective scanner regression checks, offline and deterministic."""
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from prospective_scan import scan

NOW=datetime(2026,10,26,15,0,tzinfo=timezone.utc)
def rows(symbol,interval="1m",range_="5d"):
    if interval=="1d":
        return [{"source_ts":"2026-10-23T13:30:00+00:00","close":100.0}]
    return [{"source_ts":"2026-10-26T14:58:00+00:00","close":105.0,"volume":1200,"provider":"test"}]

class ProspectiveScannerTests(unittest.TestCase):
    def test_first_seen_persists_across_scans(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/"ledger.jsonl")
            with patch("prospective_scan.fetch",side_effect=rows):
                a=scan(["TEST"],path,now=NOW)
                b=scan(["TEST"],path,now=NOW+timedelta(seconds=30))
            self.assertEqual(a["discovered"],1)
            self.assertEqual(a["validated"],1)
            self.assertEqual(b["discovered"],0)
            self.assertEqual(b["validated"],0)
            self.assertEqual(len(Path(path).read_text().splitlines()),2)

    def test_future_timestamp_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("prospective_scan.fetch",side_effect=rows):
                r=scan(["TEST"],str(Path(folder)/"ledger.jsonl"),now=NOW-timedelta(minutes=2))
            self.assertEqual(r["discovered"],0)
            self.assertEqual(r["validated"],0)

if __name__=="__main__":unittest.main()
