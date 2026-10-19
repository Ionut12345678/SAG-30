import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import radar_discovery
import radar_followup

class SnapshotCLITests(unittest.TestCase):
    def test_discovery_creates_exact_snapshot_followup_consumes(self):
        payload={"data":{"rows":[{"symbol":"ABC","pctchange":"+7.2%","lastsale":"$10.00"}],"totalRecords":1}}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            snapshot=root/"nasdaq-snapshot.json"
            discovery=root/"radar-discovery.json"
            ledger=root/"candidate-state.json"
            follow=root/"candidate-followup.json"
            with patch.object(sys,"argv",["radar_discovery.py","--snapshot",str(snapshot),"--output",str(discovery)]),patch.object(radar_discovery,"fetch_payload",return_value=payload):
                radar_discovery.main()
            self.assertEqual(json.loads(snapshot.read_text()),payload)
            self.assertEqual(json.loads(discovery.read_text())["candidates_total"],1)
            with patch.object(sys,"argv",["radar_followup.py","--snapshot",str(snapshot),"--state",str(ledger),"--out",str(follow)]),patch.object(radar_followup,"fetch_payload",side_effect=AssertionError("Unexpected second fetch")):
                radar_followup.main()
            result=json.loads(follow.read_text())
            self.assertEqual(result["status"],"UNVERIFIED_SCREENING_OBSERVED")
            self.assertTrue(result["same_snapshot_as_discovery"])
            self.assertEqual(result["new_candidates"],1)
            self.assertTrue(ledger.exists())
    def test_failed_fetch_does_not_reuse_old_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            snapshot=root/"nasdaq-snapshot.json"
            snapshot.write_text('{"data":{"rows":[{"symbol":"OLD","pctchange":"9%"}]}}')
            report=root/"radar-discovery.json"
            with patch.object(sys,"argv",["radar_discovery.py","--snapshot",str(snapshot),"--output",str(report)]),patch.object(radar_discovery,"fetch_payload",side_effect=TimeoutError):
                radar_discovery.main()
            self.assertFalse(snapshot.exists())
            self.assertEqual(json.loads(report.read_text())["scan_status"],"SOURCE_ERROR")

if __name__=="__main__":
    unittest.main()
