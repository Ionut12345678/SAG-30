"""Guard against reporting a successful step as successful state publication."""
import pathlib
import unittest


WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/shadow-lite.yml"


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

    def test_health_reports_actual_marker_and_trigger(self):
        workflow = WORKFLOW.read_text()
        self.assertIn('"state_published": pathlib.Path("shadow-lite/state-published").exists()', workflow)
        self.assertIn('"trigger_event": os.getenv("GITHUB_EVENT_NAME")', workflow)
        self.assertIn("if: ${{ always() }}", workflow)


if __name__ == "__main__":
    unittest.main()
