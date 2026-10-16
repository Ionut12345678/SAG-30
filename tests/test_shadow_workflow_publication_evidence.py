"""Guard against reporting a successful step as successful state publication."""
import pathlib
import unittest


WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/shadow-lite.yml"


@unittest.skipUnless(WORKFLOW.exists(), "Legacy SHADOW Lite workflow retired")
class ShadowPublicationEvidenceTests(unittest.TestCase):
    def test_marker_is_written_only_after_remote_put(self):
        workflow = WORKFLOW.read_text()
        persist = workflow.split("      - name: Persist first_seen", 1)[1].split(
            "      - name: Write workflow health evidence", 1
        )[0]
        put = persist.index('gh api --method PUT')
        marker = persist.index('> shadow-lite/state-published')
        self.assertLess(put, marker)
        self.assertIn('if [ "$(cat shadow-lite/should-publish)" != 1 ]; then exit 0; fi', persist)

    def test_remote_readback_precedes_publication_marker(self):
        workflow = WORKFLOW.read_text()
        persist = workflow.split("      - name: Persist first_seen", 1)[1].split(
            "      - name: Read-only post-detection", 1
        )[0]
        self.assertLess(persist.index("persisted-remote.json"), persist.index("> shadow-lite/state-published"))
        self.assertIn('if not verified:', persist)
        self.assertIn('raise SystemExit("SHADOW state readback differs', persist)

    def test_followup_is_read_only_and_artifact_is_uploaded(self):
        workflow = WORKFLOW.read_text()
        followup = workflow.split("      - name: Read-only post-detection", 1)[1].split(
            "      - name: Write workflow health evidence", 1
        )[0]
        self.assertIn("python -m radar.shadow_recover", followup)
        self.assertIn("if [ ! -f shadow-lite/state-published ]; then", followup)
        self.assertNotIn("gh api --method PUT", followup)
        self.assertIn("shadow-lite/followup.json", workflow)
        self.assertIn('"followup": os.getenv("FOLLOWUP_OUTCOME")', workflow)

    def test_health_reports_actual_marker_and_trigger(self):
        workflow = WORKFLOW.read_text()
        self.assertIn('"state_published": pathlib.Path("shadow-lite/state-published").exists()', workflow)
        self.assertIn('"trigger_event": os.getenv("GITHUB_EVENT_NAME")', workflow)
        self.assertIn("if: ${{ always() }}", workflow)


if __name__ == "__main__":
    unittest.main()
