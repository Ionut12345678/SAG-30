import unittest
from datetime import datetime
from radar.pre50_sessions import latest_completed_session


class CompletedSessionTests(unittest.TestCase):
    def test_intraday_and_publication_delay_exclude_today(self):
        for clock in ('2026-10-15T16:48:00+00:00', '2026-10-15T20:04:59+00:00'):
            self.assertEqual(latest_completed_session(datetime.fromisoformat(clock)), '2026-10-14')
        self.assertEqual(latest_completed_session(datetime.fromisoformat('2026-10-15T20:05:00+00:00')), '2026-10-15')

    def test_holiday_weekend_early_close_and_dst(self):
        cases = {
            '2026-07-03T23:15:00+00:00': '2026-07-02',
            '2026-10-18T23:15:00+00:00': '2026-10-16',
            '2026-11-27T18:06:00+00:00': '2026-11-27',
            '2026-11-02T20:30:00+00:00': '2026-10-30',
            '2026-11-02T21:06:00+00:00': '2026-11-02',
        }
        for clock, session in cases.items():
            with self.subTest(clock=clock):
                self.assertEqual(latest_completed_session(datetime.fromisoformat(clock)), session)

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError):
            latest_completed_session(datetime(2026, 10, 15))
