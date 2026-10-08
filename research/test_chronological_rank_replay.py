"""Deterministic regression tests for the read-only chronological SHADOW replay."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from chronological_rank_replay import replay

def row(ts,symbol,rank,**kw):
    return {"ts":ts,"symbol":symbol,"session":"2026-10-08","rank":rank,"selected":False,**kw}

class ReplayTests(unittest.TestCase):
    def test_hindsight_event_not_counted(self):
        rows=[row("2026-10-08T15:00:00+00:00","AAA",50,
                  observed_30_after_ts="2026-10-08T14:00:00+00:00")]
        result=replay(rows,cutoffs=(60,))["results"][0]
        self.assertEqual(result["observed_30_after_alert"],0)
        self.assertEqual(result["known_30_labels"],0)

    def test_future_event_counted(self):
        rows=[row("2026-10-08T15:00:00+00:00","AAA",50,
                  observed_30_after_ts="2026-10-08T16:00:00+00:00")]
        result=replay(rows,cutoffs=(60,))["results"][0]
        self.assertEqual(result["observed_30_after_alert"],1)

    def test_dedup_and_threshold(self):
        rows=[row("2026-10-08T15:00:00+00:00","AAA",70),
              row("2026-10-08T15:05:00+00:00","AAA",50),
              row("2026-10-08T15:00:00+00:00","BBB",110)]
        result=replay(rows,cutoffs=(60,100,120))["results"]
        self.assertEqual([x["unique_alerts"] for x in result],[1,1,2])

    def test_missing_rank_is_not_imputed(self):
        result=replay([row("2026-10-08T15:00:00+00:00","AAA",None)],cutoffs=(60,))["results"][0]
        self.assertEqual(result["unique_alerts"],0)
        self.assertTrue(result["incomplete_rank_coverage"])

    def test_reject_naive_timestamp(self):
        with self.assertRaises(ValueError):
            replay([row("2026-10-08T15:00:00","AAA",50)])

if __name__=="__main__":
    unittest.main()
