import datetime as dt
import unittest
from radar.gate0_actions_runs import collect

UTC = dt.timezone.utc


class ActionsCollectorTests(unittest.TestCase):
    def test_collect_multiple_pages(self):
        start = dt.datetime(2026, 10, 16, tzinfo=UTC)
        end = start + dt.timedelta(days=1)
        calls = []
        def fetch(page):
            calls.append(page)
            if page == 1:
                return {"workflow_runs": [{"id": i, "created_at": "2026-10-16T14:00:00Z"}
                                           for i in range(100)]}
            return {"workflow_runs": [{"id": 101, "created_at": "2026-10-16T14:05:00Z"}]}
        result = collect(fetch, start, end)
        self.assertEqual(len(result), 101)
        self.assertEqual(calls, [1, 2])

    def test_empty_page_is_not_signal_count(self):
        start = dt.datetime(2026, 10, 16, tzinfo=UTC)
        self.assertEqual(collect(lambda _: {"workflow_runs": []},
                                 start, start + dt.timedelta(days=1)), [])


if __name__ == "__main__":
    unittest.main()
