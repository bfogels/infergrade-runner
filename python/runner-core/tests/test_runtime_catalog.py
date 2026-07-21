import hashlib
import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_NAME = "infergrade/llama-cpp/b10069/macos-arm64.tar.gz"


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

        self.assertEqual(projection["signing_environment"], "review_candidate")
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


if __name__ == "__main__":
    unittest.main()
