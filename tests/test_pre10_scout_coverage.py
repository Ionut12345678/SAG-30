import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from radar.pre10_scout_coverage import audit

class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"history.sqlite"
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE scout_history(session TEXT,symbol TEXT,retrieval_ts TEXT,change_pct REAL,selected INTEGER)")
            c.executemany("INSERT INTO scout_history VALUES(?,?,?,?,?)",[
              ("2026-10-12","EARLY","2026-10-12T17:00:00Z",5,1),
              ("2026-10-12","EARLY","2026-10-12T18:00:00Z",31,1),
              ("2026-10-12","LATE","2026-10-12T17:00:00Z",12,1),
              ("2026-10-12","LATE","2026-10-12T18:00:00Z",31,1),
              ("2026-10-12","NONE","2026-10-12T18:00:00Z",60,1)])
    def tearDown(self): self.tmp.cleanup()
    def w(self,s,cls="SCOUT_MISS"):
        return {"session":"2026-10-12","symbol":s,"first_30_ts":"2026-10-12T18:00:00Z","classification_under_10":cls}
    def test_categories_avoid_inventing_earlier_observations(self):
        r=audit(self.db,{"winners":[self.w("EARLY","SHORTLIST_MISS"),self.w("LATE"),self.w("NONE")]})
        self.assertEqual(r["all_coverage_counts"],{"PRE10_SCOUT_OBSERVED":1,"FIRST_AVAILABLE_PRE30_ALREADY_GE10":1,"NO_SCOUT_SAMPLE_BEFORE_30":1})
        self.assertEqual(r["scout_miss_sessions"],2)
        self.assertEqual(r["scout_miss_coverage_counts"]["NO_SCOUT_SAMPLE_BEFORE_30"],1)
        self.assertEqual(r["cases"][0]["pre10_selected_rows"],1)
        self.assertFalse(r["buy"])
    def test_source_cause_stays_unknown(self):
        r=audit(self.db,{"winners":[self.w("LATE")]})
        self.assertIn("UNKNOWN",r["cases"][0]["provider_cause"])
    def test_missing_schema_fails_closed(self):
        with sqlite3.connect(self.db) as c:
            c.execute("DROP TABLE scout_history")
        with self.assertRaisesRegex(ValueError,"SCOUT_HISTORY_SCHEMA_INCOMPLETE"):
            audit(self.db,{"winners":[self.w("NONE")]})

if __name__=="__main__": unittest.main()
