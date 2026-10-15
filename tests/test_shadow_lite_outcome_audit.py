import unittest
from datetime import datetime, timedelta, timezone
from radar.shadow_lite import cycle


class OutcomeAuditTests(unittest.TestCase):
    def test_new_watch_is_not_claimed_as_followup(self):
        now = datetime(2026, 10, 15, 16, 48, tzinfo=timezone.utc)
        snapshot = {'latestTrade': {'t': (now - timedelta(seconds=10)).isoformat(), 'p': 109},
                    'prevDailyBar': {'c': 100}}
        state, report = cycle(now, ['ABC'], {'ABC': snapshot}, {})
        self.assertEqual(report['post_alert_unobserved_count'], 1)
        self.assertEqual(report['post_alert_observed_count'], 0)
        self.assertIsNone(report['outcome_audit']['ABC']['max_observed_price_after'])

    def test_later_trade_is_followup_evidence(self):
        now = datetime(2026, 10, 15, 16, 48, tzinfo=timezone.utc)
        before = {'latestTrade': {'t': (now - timedelta(seconds=10)).isoformat(), 'p': 109},
                  'prevDailyBar': {'c': 100}}
        state, _ = cycle(now, ['ABC'], {'ABC': before}, {})
        later = now + timedelta(minutes=5)
        after = {'latestTrade': {'t': (later - timedelta(seconds=10)).isoformat(), 'p': 115},
                 'prevDailyBar': {'c': 100}}
        state, report = cycle(later, ['ABC'], {'ABC': after}, state)
        self.assertEqual(report['post_alert_observed_count'], 1)
        self.assertEqual(report['outcome_audit']['ABC']['max_observed_price_after'], 115)
        self.assertIn(15, report['outcome_audit']['ABC']['milestones'])


if __name__ == '__main__':
    unittest.main()
