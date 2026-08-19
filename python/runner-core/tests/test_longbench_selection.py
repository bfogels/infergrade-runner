import json
import unittest
from copy import deepcopy

from infergrade import longbench_selection
from infergrade.longbench_selection import (
    ARTIFACT_SPEC_VERSION,
    BENCHMARK_ID,
    RECEIPT_ARTIFACT_KIND,
    SELECTION_DIGEST_ALGORITHM,
    SELECTION_DIGEST_CONVENTION,
    load_longbench_selection_manifest,
    verify_longbench_selection_receipt,
)
from infergrade.selection_identity import selection_digest


TIER_COUNTS = {"canary": 6, "standard": 12, "gold": 23}
TIER_SAMPLE_POLICIES = {
    "canary": "short_domain_balanced_difficulty_mixed_6_v1",
    "standard": "short_domain_difficulty_balanced_12_v1",
    "gold": "short_domain_difficulty_balanced_23_v1",
}


def _receipt_cases_metadata(tier):
    manifest = load_longbench_selection_manifest()
    count = TIER_COUNTS[tier]
    projection = deepcopy(manifest["selection_projection"][:count])
    selected_ids = list(manifest["selected_ids"][:count])
    receipt = {
        "artifact_kind": RECEIPT_ARTIFACT_KIND,
        "artifact_spec_version": ARTIFACT_SPEC_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "dataset": manifest["dataset"],
        "dataset_revision": manifest["dataset_revision"],
        "dataset_sha256": manifest["dataset_sha256"],
        "dataset_license": manifest["dataset_license"],
        "source_case_count": manifest["source_case_count"],
        "source_short_case_count": manifest["source_short_case_count"],
        "source_context_fit_case_count": manifest["source_context_fit_case_count"],
        "maximum_estimated_context_tokens": manifest["maximum_estimated_context_tokens"],
        "domain_count": manifest["domain_count"],
        "difficulty_count": manifest["difficulty_count"],
        "length_scope": manifest["length_scope"],
        "selection_policy": manifest["selection_policy"],
        "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM,
        "selection_digest_convention": SELECTION_DIGEST_CONVENTION,
        "snapshot_sha256": manifest["snapshot_sha256"],
        "tier": tier,
        "case_count": count,
        "selected_ids": selected_ids,
        "prepared_ids": list(selected_ids),
        "selection_projection": projection,
        "selection_sha256": selection_digest(selected_ids, SELECTION_DIGEST_ALGORITHM),
    }
    cases = [
        {
            "case_id": "longbench_v2/%s" % row["_id"],
            "task_id": "longbench_v2/%s" % row["_id"],
            "question_id": row["_id"],
            "category": row["domain"],
            "sub_domain": row["sub_domain"],
            "difficulty": row["difficulty"],
            "length": row["length"],
            "context_word_count": 10 + index,
            "nominal_context_bucket_tokens": 16384,
            "prompt": "prompt content is allowed in prepared cases, not receipts",
        }
        for index, row in enumerate(projection)
    ]
    metadata = {
        "benchmark_id": BENCHMARK_ID,
        "display_name": "LongBench v2 local reference",
        "case_count": count,
        "category_count": len({row["domain"] for row in projection}),
        "difficulty_count": len({row["difficulty"] for row in projection}),
        "length_scope": manifest["length_scope"],
        "minimum_context_word_count": 10,
        "maximum_context_word_count": 9 + count,
        "context_bucket_counts": {"16384": count},
        "dataset": manifest["dataset"],
        "dataset_revision": manifest["dataset_revision"],
        "dataset_sha256": manifest["dataset_sha256"],
        "dataset_license": manifest["dataset_license"],
        "snapshot_sha256": manifest["snapshot_sha256"],
        "sample_policy": TIER_SAMPLE_POLICIES[tier],
        "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM,
        "selection_digest_convention": SELECTION_DIGEST_CONVENTION,
        "selection_sha256": receipt["selection_sha256"],
    }
    return receipt, cases, metadata


class LongBenchSelectionTests(unittest.TestCase):
    def test_manifest_is_prompt_free_and_pinned(self):
        manifest = load_longbench_selection_manifest()

        self.assertEqual(manifest["benchmark_id"], BENCHMARK_ID)
        self.assertEqual(manifest["selection_sha256"], "1a5f48517a31dc80083700955b92d9524cba2d863448209956e2cf1b423079a3")
        self.assertEqual(manifest["tier_prefix_counts"], TIER_COUNTS)
        serialized = json.dumps(manifest, sort_keys=True)
        for forbidden in ("answer", "choice_A", "choice_B", "choice_C", "choice_D", "context", "prompt", "question"):
            self.assertNotIn('"%s"' % forbidden, serialized)

    def test_manifest_rejects_top_level_extra_fields_without_echoing_private_values(self):
        manifest = load_longbench_selection_manifest()
        manifest["unexpected_prompt_free_field"] = "TOP SECRET MANIFEST DATA"

        with self.assertRaisesRegex(ValueError, "fields are not allowlisted") as raised:
            longbench_selection._validate_manifest(manifest)
        self.assertNotIn("TOP SECRET MANIFEST DATA", str(raised.exception))

    def test_receipt_accepts_each_tier_and_binds_metadata(self):
        for tier in TIER_COUNTS:
            with self.subTest(tier=tier):
                receipt, cases, metadata = _receipt_cases_metadata(tier)
                result = verify_longbench_selection_receipt(receipt, cases, tier, metadata)
                self.assertEqual(result["tier"], tier)
                self.assertEqual(result["case_count"], TIER_COUNTS[tier])
                self.assertEqual(result["selection_sha256"], receipt["selection_sha256"])

    def test_receipt_rejects_metadata_order_and_projection_tampering(self):
        receipt, cases, metadata = _receipt_cases_metadata("canary")

        tampered_metadata = deepcopy(metadata)
        tampered_metadata["dataset_revision"] = "attacker-revision"
        with self.assertRaisesRegex(ValueError, "metadata mismatch: dataset_revision"):
            verify_longbench_selection_receipt(receipt, cases, "canary", tampered_metadata)

        tampered_receipt = deepcopy(receipt)
        tampered_receipt["selected_ids"] = list(reversed(tampered_receipt["selected_ids"]))
        with self.assertRaisesRegex(ValueError, "selected ID order mismatch"):
            verify_longbench_selection_receipt(tampered_receipt, cases, "canary", metadata)

        tampered_receipt = deepcopy(receipt)
        tampered_receipt["selection_projection"][0]["domain"] = "tampered-domain"
        with self.assertRaisesRegex(ValueError, "selection projection mismatch"):
            verify_longbench_selection_receipt(tampered_receipt, cases, "canary", metadata)

        tampered_cases = list(reversed(cases))
        with self.assertRaisesRegex(ValueError, "prepared case IDs mismatch"):
            verify_longbench_selection_receipt(receipt, tampered_cases, "canary", metadata)

    def test_receipt_rejects_unknown_duplicate_extra_and_privacy_fields(self):
        receipt, cases, metadata = _receipt_cases_metadata("canary")

        tampered_receipt = deepcopy(receipt)
        tampered_receipt["selected_ids"][0] = "attacker-raw-id-with-secret"
        with self.assertRaises(ValueError) as raised:
            verify_longbench_selection_receipt(tampered_receipt, cases, "canary", metadata)
        self.assertNotIn("attacker-raw-id-with-secret", str(raised.exception))

        tampered_receipt = deepcopy(receipt)
        tampered_receipt["selected_ids"][1] = tampered_receipt["selected_ids"][0]
        with self.assertRaisesRegex(ValueError, "duplicate IDs"):
            verify_longbench_selection_receipt(tampered_receipt, cases, "canary", metadata)

        tampered_receipt = deepcopy(receipt)
        tampered_receipt["prompt"] = "TOP SECRET PROMPT CONTENT"
        with self.assertRaises(ValueError) as raised:
            verify_longbench_selection_receipt(tampered_receipt, cases, "canary", metadata)
        self.assertNotIn("TOP SECRET PROMPT CONTENT", str(raised.exception))

    def test_receipt_rejects_coordinated_truncation_and_metadata_digest_drift(self):
        receipt, cases, metadata = _receipt_cases_metadata("standard")

        tampered_receipt = deepcopy(receipt)
        tampered_receipt["selected_ids"] = tampered_receipt["selected_ids"][:-1]
        tampered_receipt["prepared_ids"] = tampered_receipt["prepared_ids"][:-1]
        tampered_receipt["selection_projection"] = tampered_receipt["selection_projection"][:-1]
        tampered_receipt["case_count"] = 11
        tampered_receipt["selection_sha256"] = selection_digest(
            tampered_receipt["selected_ids"], SELECTION_DIGEST_ALGORITHM
        )
        with self.assertRaises(ValueError):
            verify_longbench_selection_receipt(tampered_receipt, cases[:-1], "standard", metadata)

        tampered_metadata = deepcopy(metadata)
        tampered_metadata["selection_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "metadata mismatch: selection_sha256"):
            verify_longbench_selection_receipt(receipt, cases, "standard", tampered_metadata)


if __name__ == "__main__":
    unittest.main()
