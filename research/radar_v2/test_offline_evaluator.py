"""Execute from repository root: python -m unittest discover -s research/radar_v2 -p 'test_offline_*.py'"""
import unittest
from datetime import datetime, timedelta, timezone
from research.radar_v2.offline_evaluator import Event, evaluate

T = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
def q(price, source=T, ingest=T, volume=100, reference=100, symbol="XYZ"):
    return Event(symbol, source, ingest, price, reference, volume, "test")

class TestOfflineEvaluation(unittest.TestCase):
    def test_touch(self):
        r = evaluate([q(105), q(121, T+timedelta(minutes=1), T+timedelta(minutes=1))])
        self.assertEqual(r["validated_milestone_counts"]["20"], 1)
    def test_no_prior_high(self):
        r = evaluate([q(105), q(130, T-timedelta(seconds=1), T+timedelta(seconds=1))])
        self.assertEqual(r["validated_milestone_counts"]["15"], 0)
    def test_zero_volume(self):
        r = evaluate([q(105), q(150, T+timedelta(minutes=1), T+timedelta(minutes=1), volume=0)])
        self.assertEqual(r["validated_milestone_counts"]["50"], 0)
    def test_stale(self):
        self.assertEqual(evaluate([q(105, T, T+timedelta(minutes=6))])["discoveries"], 0)
    def test_duplicate(self):
        self.assertEqual(evaluate([q(105), q(105)])["rejections"]["duplicate"], 1)
    def test_reference_changed(self):
        r = evaluate([q(105), q(121, T+timedelta(minutes=1), T+timedelta(minutes=1), reference=90)])
        self.assertEqual(r["validated_milestone_counts"]["20"], 0)
    def test_future_source(self):
        self.assertEqual(evaluate([q(105, T+timedelta(seconds=1), T)])["discoveries"], 0)
    def test_ingest_order(self):
        r = evaluate([q(121, T+timedelta(minutes=1), T+timedelta(minutes=1)), q(105)])
        self.assertEqual(r["validated_milestone_counts"]["20"], 1)
