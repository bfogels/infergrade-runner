import hashlib
import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_NAME = "infergrade/llama-cpp/b10069/macos-arm64.tar.gz"
BONSAI_TARGET_NAME = (
    "infergrade/prism-llama-cpp/prism-b9596-9fcaed7/macos-arm64.tar.gz"
)


def load_json(relative_path):
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


class RuntimeCatalogContractTests(unittest.TestCase):
    def test_projection_is_bound_to_signed_targets_and_exact_qualification(self):
        signed_targets_path = REPO_ROOT / "runtime/catalog/signed/targets.json"
        signed_targets_bytes = signed_targets_path.read_bytes()
        signed_targets = json.loads(signed_targets_bytes)
        projection = load_json("schemas/runtime_trust_catalog.json")
        qualification = load_json(
            "runtime/qualification/llama-cpp-b10069-macos-arm64.json"
        )

        self.assertEqual(
            projection["targets_metadata_sha256"],
            hashlib.sha256(signed_targets_bytes).hexdigest(),
        )
        self.assertEqual(
            projection["targets_metadata_version"],
            signed_targets["signed"]["version"],
        )
        projected_target = next(
            target for target in projection["targets"] if target["target_name"] == TARGET_NAME
        )
        signed_target = signed_targets["signed"]["targets"][TARGET_NAME]
        custom = signed_target["custom"]
        self.assertEqual(projected_target["runtime_build_id"], custom["runtime_build_id"])
        self.assertEqual(
            projected_target["content_manifest_sha256"],
            custom["content_manifest_sha256"],
        )
        self.assertEqual(projected_target["archive_sha256"], signed_target["sha256"])
        self.assertEqual(
            qualification["runtime"]["catalog_targets_metadata_sha256"],
            projection["targets_metadata_sha256"],
        )
        self.assertEqual(
            qualification["runtime"]["runtime_build_id"],
            projected_target["runtime_build_id"],
        )

        projected_assertions = {
            item["bundle_id"]: item for item in projected_target["validation_assertions"]
        }
        qualified_assertions = {
            item["bundle_id"]: item for item in qualification["assertions"]
        }
        self.assertEqual(set(projected_assertions), set(qualified_assertions))
        for bundle_id, assertion in projected_assertions.items():
            self.assertEqual(
                assertion["model_artifact_sha256"],
                qualified_assertions[bundle_id]["model_artifact_sha256"],
            )
            self.assertFalse(assertion["published"])

    def test_candidate_dimensions_remain_separate_and_scope_is_narrow(self):
        projection = load_json("schemas/runtime_trust_catalog.json")
        target = next(
            target for target in projection["targets"] if target["target_name"] == TARGET_NAME
        )
        qualification = load_json(
            "runtime/qualification/llama-cpp-b10069-macos-arm64.json"
        )

        self.assertEqual(projection["signing_environment"], "production")
        self.assertEqual(target["maturity"], "reviewed_candidate")
        self.assertEqual(target["support_tier"], "candidate")
        self.assertEqual(
            target["compatibility_status"],
            "exact_artifact_standard_depth_validated",
        )
        self.assertEqual(
            qualification["claim_scope"],
            "exact_artifacts_on_recorded_hardware_only",
        )
        self.assertFalse(qualification["publication"]["published"])

    def test_bonsai_candidate_is_staged_without_overclaiming_active_trust(self):
        source = load_json("runtime/catalog/catalog-source.json")
        qualification = load_json(
            "runtime/qualification/llama-prism-b9596-bonsai-q1-macos-arm64.json"
        )
        gemma4_qualification = load_json(
            "runtime/qualification/llama-cpp-b10069-gemma4-12b-q4-k-m-macos-arm64.json"
        )
        active_targets = load_json("runtime/catalog/signed/targets.json")

        self.assertEqual(source["activation_status"], "staged_candidate")
        self.assertEqual(
            source["versions"]["targets"], active_targets["signed"]["version"] + 1
        )
        self.assertNotIn(BONSAI_TARGET_NAME, active_targets["signed"]["targets"])
        target = source["targets"][BONSAI_TARGET_NAME]
        self.assertEqual(target["custom"]["runtime_family"], "llama.cpp-prism")
        self.assertEqual(target["custom"]["support_tier"], "candidate")
        self.assertEqual(
            target["custom"]["compatibility_status"],
            "exact_artifact_standard_depth_validated",
        )
        self.assertEqual(
            qualification["runtime"]["catalog_activation_status"],
            "staged_candidate",
        )
        self.assertEqual(
            qualification["runtime"]["signed_catalog_state"], "not_yet_active"
        )
        self.assertEqual(
            qualification["assertions"][0]["mmlu_pro_malformed_output_count"], 0
        )
        self.assertFalse(qualification["publication"]["published"])

        upstream_target = source["targets"][TARGET_NAME]
        assertions = {
            item["model_artifact_sha256"]: item
            for item in upstream_target["custom"]["validation_assertions"]
        }
        gemma4_sha256 = (
            "0a270ec9fe6b34f4a0d33992b6135117b484ebc4766ab76b51d4ae8c457e4c42"
        )
        self.assertEqual(
            assertions[gemma4_sha256]["bundle_id"],
            "qb_20260722_161200_f40ca06a",
        )
        self.assertEqual(assertions[gemma4_sha256]["result_status"], "valid_comparable")
        self.assertFalse(assertions[gemma4_sha256]["published"])
        self.assertEqual(
            gemma4_qualification["assertions"][0]["bundle_id"],
            assertions[gemma4_sha256]["bundle_id"],
        )
        self.assertEqual(
            gemma4_qualification["assertions"][0]["mmlu_pro_malformed_output_count"],
            0,
        )
        self.assertEqual(
            gemma4_qualification["runtime"]["signed_catalog_assertion_state"],
            "staged_not_active",
        )


if __name__ == "__main__":
    unittest.main()
