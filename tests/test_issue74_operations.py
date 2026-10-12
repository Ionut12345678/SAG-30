import unittest
from datetime import datetime, timezone
from radar.cadence import dispatch_wait
from radar.health import health_reasons

class OperationsTests(unittest.TestCase):
    def test_compensates_dispatch_overhead(self):
        plan=dispatch_wait(['2026-10-12T17:05:16+00:00','2026-10-12T17:00:00+00:00'],datetime(2026,10,12,17,8,36,tzinfo=timezone.utc))
        self.assertEqual(plan['wait_seconds'],84)
        self.assertEqual(plan['latency_compensation_seconds'],16)
    def test_overnight_outage_and_invalid_gaps_do_not_accelerate(self):
        now=datetime(2026,10,12,17,8,tzinfo=timezone.utc)
        for previous in ['2026-10-09T17:00:00+00:00','2026-10-12T16:00:00+00:00','2026-10-12T18:00:00+00:00']:
            self.assertEqual(dispatch_wait(['2026-10-12T17:05:00+00:00',previous],now)['latency_compensation_seconds'],0)
    def test_compensation_bounded_and_slow_cycle_never_waits(self):
        plan=dispatch_wait(['2026-10-12T17:09:00+00:00','2026-10-12T17:00:00+00:00'],datetime(2026,10,12,17,20,tzinfo=timezone.utc))
        self.assertEqual(plan['latency_compensation_seconds'],60)
        self.assertEqual(plan['wait_seconds'],0)
    def test_independent_reason_codes(self):
        h={'workflow':{'scan_rc':0,'bridge_rc':0},'latest_run':{'status':'DISCOVERY_OK'},'fast_path':{'status':'CURRENT_SHADOW_EVIDENCE'},'pending_bridge_events':0,'observation_window_active':True,'checkpoint_is_current_cycle':True,'fast_scout':{'status':'PASS'},'cadence':{'status':'MISSED_TARGET'}}
        self.assertEqual(health_reasons(h),['CADENCE_MISSED_TARGET'])
        h['fast_scout']['status']='DATA_GAP'
        self.assertEqual(health_reasons(h),['CADENCE_MISSED_TARGET','SCOUT_DATA_GAP'])

class FreshnessTests(unittest.TestCase):
    def test_quote_age_and_execution_remain_separate(self):
        from radar.freshness import quote_diagnostic
        quote={'latestQuote':{'t':'2026-10-12T17:00:00Z','bp':10,'ap':10.1}}
        fresh=quote_diagnostic(quote,'2026-10-12T17:01:00+00:00')
        self.assertEqual(fresh['status'],'FRESH_QUOTE_ONLY')
        self.assertEqual(fresh['execution_actionable'],'UNKNOWN')
        self.assertEqual(fresh['halt_status'],'UNKNOWN')
        self.assertEqual(quote_diagnostic(quote,'2026-10-12T17:10:00Z')['reason'],'STALE_QUOTE')
        self.assertEqual(quote_diagnostic(quote,'2026-10-12T16:59:00Z')['reason'],'FUTURE_QUOTE')
    def test_missing_crossed_and_invalid_quotes(self):
        from radar.freshness import quote_diagnostic
        self.assertEqual(quote_diagnostic({},'2026-10-12T17:01:00Z')['reason'],'MISSING_QUOTE')
        for bid,ask,reason in [(11,10,'CROSSED_QUOTE'),(float('nan'),10,'INVALID_BID_ASK'),(True,10,'INVALID_BID_ASK')]:
            self.assertEqual(quote_diagnostic({'latestQuote':{'t':'2026-10-12T17:00:00Z','bp':bid,'ap':ask}},'2026-10-12T17:01:00Z')['reason'],reason)

class CadenceFeedbackTests(unittest.TestCase):
    def test_stable_latency_retains_compensation_and_low_gap_reduces_it(self):
        now=datetime(2026,10,12,17,8,tzinfo=timezone.utc)
        self.assertEqual(dispatch_wait(['2026-10-12T17:05:00+00:00','2026-10-12T17:00:00+00:00'],now,previous_compensation=16)['latency_compensation_seconds'],16)
        self.assertEqual(dispatch_wait(['2026-10-12T17:04:50+00:00','2026-10-12T17:00:00+00:00'],now,previous_compensation=16)['latency_compensation_seconds'],6)
