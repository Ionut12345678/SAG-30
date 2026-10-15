import unittest
from unittest.mock import patch
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from radar.pre50 import scan


class TestPre50SessionGuard(unittest.TestCase):
    def test_scan_reports_latest_observed_date(self):
        report = scan({'ABC': [{'date': '2026-10-14'}]})
        self.assertEqual(report['as_of'], '2026-10-14')
        self.assertEqual(report['candidates'], [])

    def test_stale_symbol_detected(self):
        report = scan({'ABC': [{'date': '2026-10-14'}], 'XYZ': [{'date': '2026-10-15'}]})
        self.assertEqual(report['stale_symbols'], ['ABC'])


if __name__ == '__main__':
    unittest.main()
