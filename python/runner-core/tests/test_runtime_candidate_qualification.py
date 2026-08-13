import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUALIFICATION_PATH = (
    REPO_ROOT
    / "runtime/qualification/llama-cpp-b10375-minicpm5-1b-q4-k-m-macos-arm64.json"
)


class RuntimeCandidateQualificationTests(unittest.TestCase):
    def test_b10375_qualification_is_exact_and_not_catalog_promoted(self):
        qualification = json.loads(QUALIFICATION_PATH.read_text(encoding="utf-8"))
        runtime = qualification["runtime"]
        assertion = qualification["assertions"][0]

        self.assertEqual(qualification["status"], "valid_comparable")
        self.assertEqual(
            qualification["claim_scope"],
            "exact_artifact_on_recorded_hardware_only",
        )
        self.assertEqual(runtime["catalog_activation_status"], "not_staged")
        self.assertEqual(runtime["signed_catalog_assertion_state"], "absent")
        self.assertEqual(runtime["upstream"]["tag"], "b10375")
        self.assertEqual(runtime["maturity"], "reviewed_candidate")
        self.assertEqual(runtime["support_tier"], "candidate")
        self.assertEqual(runtime["provenance_strength"], "checksum_verified")
        self.assertFalse(runtime["independent_signature_verified"])
        self.assertEqual(runtime["content_manifest_file_count"], 61)
        for field in (
            "runtime_build_id",
            "content_manifest_sha256",
            "archive_sha256",
            "source_assertion_id",
        ):
            self.assertRegex(runtime[field], r"^[0-9a-f]{64}$")

        self.assertTrue(assertion["bundle_valid"])
        self.assertEqual(assertion["comparison_grade"], "comparable")
        self.assertEqual(assertion["receipt_prelaunch"], "passed")
        self.assertEqual(assertion["receipt_postrun"], "passed")
        self.assertEqual(assertion["ifeval_model_output_failure_count"], 4)
        self.assertEqual(assertion["ifeval_output_shape_gate"], "passed")
        self.assertEqual(
            assertion["assistant_compositional_malformed_output_count"],
            24,
        )
        self.assertEqual(assertion["capability_score"], 0.081)
        self.assertTrue(assertion["capability_score_ready"])
        self.assertFalse(qualification["publication"]["published"])


if __name__ == "__main__":
    unittest.main()
