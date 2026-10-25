"""Paper ledger invariant tests: idempotency, next-session fills and future-only outcomes."""
import unittest
from datetime import date,timedelta
from unittest.mock import patch
from paper_cycle import cycle

def bars():
    d=date(2026,1,1)
    return [{"date":d+timedelta(days=i),"open":100+i,"high":101+i,
             "low":99+i,"close":100+i,"volume":1000} for i in range(90)]

class PaperCycleTests(unittest.TestCase):
    def test_two_cycles_do_not_duplicate_signals(self):
        b=bars();ledger={"version":1,"signals":[],"runs":[]}
        with patch("paper_cycle.select_signal",return_value=True):
            first,_=cycle({"AAA":b},ledger,"one","2026-01-01T00:00:00Z")
            second,_=cycle({"AAA":b},first,"two","2026-01-01T01:00:00Z")
        self.assertEqual(len(first["signals"]),2)
        self.assertEqual(len(second["signals"]),2)
        self.assertEqual(len(second["runs"]),2)
        self.assertEqual(second["runs"][-1]["new_signals"],0)
        self.assertIsNone(second["signals"][0]["entry_date"])

    def test_next_open_and_1day_only_after_future_bars(self):
        b=bars();ledger={"version":1,"signals":[],"runs":[]}
        with patch("paper_cycle.select_signal",return_value=True):
            first,_=cycle({"AAA":b[:83]},ledger,"one","2026-01-01T00:00:00Z")
        record=first["signals"][0]
        self.assertIsNone(record["entry_open"])
        with patch("paper_cycle.select_signal",return_value=False):
            second,_=cycle({"AAA":b[:85]},first,"two","2026-01-02T00:00:00Z")
        record=second["signals"][0]
        self.assertEqual(record["entry_date"],str(b[83]["date"]))
        self.assertEqual(record["entry_open"],b[83]["open"])
        self.assertIn("1",record["outcomes"])
        self.assertNotIn("5",record["outcomes"])

    def test_invalid_state_fails_closed(self):
        with self.assertRaises(ValueError):
            cycle({"AAA":bars()},{"version":9,"signals":[]},"run","2026-01-01")
if __name__=="__main__":unittest.main()
