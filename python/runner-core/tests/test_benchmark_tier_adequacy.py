import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

import infergrade.benchmark_tier_adequacy as tier_adequacy
from infergrade.benchmark_catalog import load_capability_catalog
from infergrade.benchmark_tier_adequacy import (
    audit_benchmark_tier_adequacy,
    load_static_fixture_manifest,
)
from infergrade.selection_identity import (
    SORTED_JSON_STRING_ARRAY_SHA256_V1,
    SORTED_UTF8_NEWLINE_SHA256_V1,
    selection_digest,
)


class BenchmarkTierAdequacyTests(unittest.TestCase):
    def test_current_tier_sampling_contracts_are_complete(self):
        report = audit_benchmark_tier_adequacy(load_capability_catalog())

        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["artifact_spec_version"], "0.4.0")
        self.assertEqual(report["varying_tier_benchmark_count"], 15)
        self.assertEqual(report["materialized_native_fixture_count"], 7)
        self.assertEqual(report["native_tier_coverage_contract_count"], 3)
        self.assertEqual(report["verified_static_fixture_manifest_count"], 1)
        self.assertEqual(report["verified_tier_coverage_contract_count"], 4)
        self.assertEqual(report["declared_selection_digest_algorithm_count"], 15)
        self.assertEqual(report["materialized_selection_digest_verified_count"], 8)
        self.assertEqual(report["runtime_only_selection_digest_contract_count"], 7)
        self.assertEqual(report["errors"], [])
        self.assertTrue(all(item["ready"] for item in report["benchmarks"]))
        by_id = {item["benchmark_id"]: item for item in report["benchmarks"]}
        reasoning = by_id["reasoning_constraint_stress_v1"]["fixture_verification"]
        self.assertEqual(reasoning["status"], "materialized_verified")
        self.assertEqual(reasoning["source_fixture_case_count"], 48)
        self.assertTrue(reasoning["tier_coverage_contract"])
        self.assertTrue(
            all(
                requirement["ready"]
                for tier in reasoning["tiers"]
                for requirement in tier["coverage_requirements"]
            )
        )
        repository_edit = by_id["repository_edit_smoke_v1"]["fixture_verification"]
        self.assertEqual(repository_edit["status"], "source_fixture_verified")
        self.assertEqual(repository_edit["source_fixture_case_count"], 8)
        self.assertEqual(
            repository_edit["source_fixture_sha256"],
            "0630c9d2781c5fc49188392ec76fa3b658c9f22033bc34dee2d53ddc6577e29a",
        )
        self.assertTrue(repository_edit["tier_coverage_contract"])
        self.assertEqual(
            repository_edit["selection_digest_algorithm"],
            SORTED_UTF8_NEWLINE_SHA256_V1,
        )
        self.assertTrue(repository_edit["selection_digest_verified"])
        self.assertEqual(
            repository_edit["tiers"][-1]["selection_sha256"],
            selection_digest(
                [item["task_id"] for item in load_static_fixture_manifest("repository_edit_smoke_v1")["cases"]],
                SORTED_UTF8_NEWLINE_SHA256_V1,
            ),
        )
        self.assertTrue(
            all(
                requirement["ready"]
                for tier in repository_edit["tiers"]
                for requirement in tier["coverage_requirements"]
            )
        )

    def test_repository_edit_source_fixture_matches_bundled_manifest(self):
        manifest = load_static_fixture_manifest("repository_edit_smoke_v1")

        self.assertEqual(manifest["benchmark_id"], "repository_edit_smoke_v1")
        self.assertEqual(len(manifest["cases"]), 8)
        self.assertEqual(
            [item["category"] for item in manifest["cases"][:2]],
            ["state_and_time", "data_transformation"],
        )

    def test_repository_edit_source_fixture_hash_drift_fails_closed(self):
        manifest = load_static_fixture_manifest("repository_edit_smoke_v1")
        source_path = tier_adequacy._static_source_fixture_path()
        self.assertIsNotNone(source_path)

        with tempfile.TemporaryDirectory() as tempdir:
            drifted_path = Path(tempdir, "fixtures.json")
            drifted_path.write_bytes(source_path.read_bytes() + b"\n")
            with mock.patch.object(
                tier_adequacy,
                "_static_source_fixture_path",
                return_value=drifted_path,
            ):
                status, errors = tier_adequacy._verify_static_source_fixture(manifest)

        self.assertEqual(status, "source_fixture_invalid")
        self.assertIn("static_source_fixture_sha256_mismatch", errors)

    def test_missing_or_stale_policy_fails_closed(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"].pop("ifeval")
        catalog["tier_sampling_policies"]["evalplus_mbpp"]["case_limits"][
            "canary"
        ] = 20
        catalog["tier_sampling_policies"]["bfcl_local_reference_v1"][
            "selection_identity_policy"
        ] = "source_snapshot_only"

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertFalse(report["ready"])
        self.assertIn("ifeval:missing_tier_sampling_policy", report["errors"])
        self.assertIn("evalplus_mbpp:case_limits_mismatch", report["errors"])
        self.assertIn(
            "bfcl_local_reference_v1:selection_identity_not_exact",
            report["errors"],
        )

    def test_balanced_strategy_requires_declared_strata(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["stateful_tool_loop_diagnostic_v1"][
            "stratification_fields"
        ] = []

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertIn(
            "stateful_tool_loop_diagnostic_v1:missing_stratification_fields",
            report["errors"],
        )

    def test_missing_or_execution_incompatible_digest_algorithm_fails_closed(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["ifeval"].pop(
            "selection_digest_algorithm"
        )
        catalog["tier_sampling_policies"]["reasoning_exact_answer_v1"][
            "selection_digest_algorithm"
        ] = SORTED_UTF8_NEWLINE_SHA256_V1

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertIn(
            "ifeval:selection_digest_algorithm_invalid",
            report["errors"],
        )
        self.assertIn(
            "reasoning_exact_answer_v1:selection_digest_algorithm_mismatch",
            report["errors"],
        )

    def test_selection_digest_serialization_is_explicit_and_order_independent(self):
        case_ids = ["case-b", "case-a"]

        self.assertEqual(
            selection_digest(case_ids, SORTED_JSON_STRING_ARRAY_SHA256_V1),
            selection_digest(reversed(case_ids), SORTED_JSON_STRING_ARRAY_SHA256_V1),
        )
        self.assertEqual(
            selection_digest(case_ids, SORTED_UTF8_NEWLINE_SHA256_V1),
            selection_digest(reversed(case_ids), SORTED_UTF8_NEWLINE_SHA256_V1),
        )
        self.assertNotEqual(
            selection_digest(case_ids, SORTED_JSON_STRING_ARRAY_SHA256_V1),
            selection_digest(case_ids, SORTED_UTF8_NEWLINE_SHA256_V1),
        )

    def test_pinned_materialized_selection_rejects_case_id_mutation(self):
        catalog = deepcopy(load_capability_catalog())
        spec = tier_adequacy.CAPABILITY_BENCHMARKS["reasoning_exact_answer_v1"]
        cases = tier_adequacy._native_benchmark_cases(spec)
        mutated = [dict(case) for case in cases]
        mutated[0]["task_id"] = "reasoning_exact_answer_v1/mutated"

        with mock.patch.object(tier_adequacy, "_native_benchmark_cases", return_value=mutated):
            report = audit_benchmark_tier_adequacy(catalog)

        self.assertIn(
            "reasoning_exact_answer_v1:native_fixture_expected_tier_selection_digest_mismatch:canary",
            report["errors"],
        )

    def test_pinned_materialized_selection_rejects_missing_tier_and_wrong_count(self):
        catalog = deepcopy(load_capability_catalog())
        expected = catalog["tier_sampling_policies"]["context_retrieval_reference_v1"][
            "expected_tier_selections"
        ]
        expected.pop("standard")
        expected["gold"]["case_count"] = 5

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertIn(
            "context_retrieval_reference_v1:native_fixture_expected_tier_selection_missing_tier:standard",
            report["errors"],
        )
        self.assertIn(
            "context_retrieval_reference_v1:native_fixture_expected_tier_selection_case_count_mismatch:gold",
            report["errors"],
        )

    def test_pinned_materialized_selection_rejects_expected_digest_mutation(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["repository_edit_smoke_v1"][
            "expected_tier_selections"
        ]["gold"]["selection_sha256"] = "0" * 64

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertIn(
            "repository_edit_smoke_v1:static_fixture_manifest_expected_tier_selection_digest_mismatch:gold",
            report["errors"],
        )

    def test_native_strata_require_executable_per_tier_coverage_contracts(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["reasoning_constraint_stress_v1"].pop(
            "tier_coverage_requirements"
        )

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertFalse(report["ready"])
        self.assertIn(
            "reasoning_constraint_stress_v1:missing_tier_coverage_requirements",
            report["errors"],
        )

    def test_native_tier_coverage_fails_when_required_values_are_absent(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["stateful_tool_loop_diagnostic_v1"][
            "tier_coverage_requirements"
        ]["canary"]["variant"]["required_values"].append("unsafe_mutation")

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertFalse(report["ready"])
        self.assertIn(
            "stateful_tool_loop_diagnostic_v1:tier_coverage_missing_required_values:canary:variant",
            report["errors"],
        )

    def test_native_tier_coverage_fails_when_case_floor_is_too_high(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["context_retrieval_reference_v1"][
            "tier_coverage_requirements"
        ]["standard"]["context_bucket_tokens"][
            "minimum_cases_per_required_value"
        ] = 2

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertFalse(report["ready"])
        self.assertIn(
            "context_retrieval_reference_v1:tier_coverage_under_minimum_cases:standard:context_bucket_tokens",
            report["errors"],
        )

    def test_repository_edit_tier_coverage_fails_when_category_is_absent(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["repository_edit_smoke_v1"][
            "tier_coverage_requirements"
        ]["standard"]["category"]["required_values"].append("database_migration")

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertFalse(report["ready"])
        self.assertIn(
            "repository_edit_smoke_v1:tier_coverage_missing_required_values:standard:category",
            report["errors"],
        )


if __name__ == "__main__":
    unittest.main()
