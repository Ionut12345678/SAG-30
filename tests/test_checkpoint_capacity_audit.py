import unittest
from radar.checkpoint_capacity_audit import diagnose
from radar.checkpoint import FORMAT, PART_BYTES

def checkpoint(sizes=(67108864,35000000)):
    return {"format":FORMAT, "parts":[{"name":f"radar.sqlite3.gz.part-{i:05d}",
           "bytes":b,"sha256":"a"*64} for i,b in enumerate(sizes)],
           "compressed_bytes":sum(sizes),"journals":[]}

class CapacityAuditTests(unittest.TestCase):
    def test_total_over_90mib_does_not_imply_bad_part(self):
        x=diagnose(checkpoint())
        self.assertIn("TOTAL_COMPRESSED_GT_90_MIB", x["reasons"])
        self.assertNotIn("PART_GIT_BLOB_LIMIT", x["reasons"])
        self.assertGreater(x["part_headroom_bytes"],0)
        self.assertFalse(x["restore_verified"])

    def test_small_checkpoint_is_structurally_passable(self):
        x=diagnose(checkpoint((1000000,)), checkpoint((1000000,)))
        self.assertEqual(x["status"],"STRUCTURAL_CHECK_PASS")

    def test_growth_is_explicit(self):
        x=diagnose(checkpoint(),checkpoint((67108864,34000000)))
        self.assertEqual(x["compressed_growth_bytes_vs_previous"],1000000)
        self.assertIn("COMPRESSED_CHECKPOINT_GROWING",x["reasons"])

    def test_bad_part_order_fails_closed(self):
        x=checkpoint()
        x["parts"][0]["name"]="unsafe"
        self.assertEqual(diagnose(x)["status"],"INVALID_MANIFEST")

    def test_previous_invalid_is_not_silently_used(self):
        x=diagnose(checkpoint(),{"format":"bad"})
        self.assertIn("PREVIOUS_MANIFEST_INVALID",x["reasons"])
        self.assertIsNone(x["compressed_growth_bytes_vs_previous"])

    def test_previous_audit_artifact_supplies_growth_without_git_parent(self):
        x = diagnose(checkpoint(), previous_report={"compressed_bytes_total": 101000000})
        self.assertEqual(x["compressed_growth_bytes_vs_previous"], 1108864)
        self.assertEqual(x["growth_reference"], "PREVIOUS_AUDIT_ARTIFACT")
        self.assertIn("COMPRESSED_CHECKPOINT_GROWING", x["reasons"])

    def test_missing_previous_reference_is_explicit(self):
        x = diagnose(checkpoint())
        self.assertIsNone(x["compressed_growth_bytes_vs_previous"])
        self.assertEqual(x["growth_reference"], "NONE")
        self.assertIn("PREVIOUS_SIZE_REFERENCE_UNAVAILABLE", x["reasons"])

    def test_invalid_prior_audit_artifact_is_not_used(self):
        x = diagnose(checkpoint(), previous_report={"compressed_bytes_total": "unknown"})
        self.assertIsNone(x["compressed_growth_bytes_vs_previous"])
        self.assertIn("PREVIOUS_AUDIT_REPORT_INVALID", x["reasons"])

    def test_real_previous_manifest_takes_priority_over_audit_artifact(self):
        x = diagnose(checkpoint(), checkpoint((67108864, 34000000)),
                     {"compressed_bytes_total": 1})
        self.assertEqual(x["compressed_growth_bytes_vs_previous"], 1000000)
        self.assertEqual(x["growth_reference"], "PREVIOUS_MANIFEST")


if __name__=="__main__":
    unittest.main()
