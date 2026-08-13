import unittest
from copy import deepcopy

from infergrade.benchmark_adequacy import (
    audit_benchmark_adequacy,
    validate_benchmark_adequacy_metadata,
)
from infergrade.benchmark_catalog import load_capability_catalog


class BenchmarkAdequacyTests(unittest.TestCase):
    def test_catalog_metadata_is_valid_and_narrow_claims_are_structurally_covered(self):
        catalog = load_capability_catalog()

        self.assertEqual(validate_benchmark_adequacy_metadata(catalog), [])
        report = audit_benchmark_adequacy(catalog)

        self.assertEqual(report["artifact_spec_version"], "0.2.0")
        self.assertTrue(report["scoped_claim_coverage_ready"])
        self.assertFalse(report["broad_surface_coverage_ready"])
        self.assertEqual(len(report["surfaces"]), 3)

    def test_report_exposes_current_broad_coverage_and_headroom_gaps(self):
        report = audit_benchmark_adequacy(load_capability_catalog())
        by_surface = {item["surface_id"]: item for item in report["surfaces"]}

        assistant = by_surface["local_assistant_capability"]
        self.assertEqual(
            assistant["empirical_priority_facet_policy"]["policy_id"],
            "priority_facet_evidence_gate_v2",
        )
        self.assertEqual(
            assistant["empirical_priority_facet_policy"]["minimum_observations"],
            16,
        )
        self.assertIn("assistant_preference_quality", assistant["planned_only_priority_facets"])
        self.assertIn("tool_use", assistant["diagnostic_facets_covered"])
        self.assertIn("stateful_tool_use", assistant["diagnostic_facets_covered"])
        self.assertIn("tool_use", assistant["freshness"]["runnable_refreshable_facets"])
        self.assertEqual(
            assistant["known_diagnostic_saturation_risks"],
            ["multiturn_chat_memory_v1"],
        )
        self.assertTrue(assistant["freshness"]["ready"])

        coding = by_surface["local_coding_capability"]
        self.assertIn("repository_code_editing", coding["diagnostic_facets_covered"])
        self.assertIn("coding_static_repair_v1", coding["known_headline_saturation_risks"])
        self.assertIn("real_repository_issue_resolution", coding["planned_only_priority_facets"])

        reasoning = by_surface["local_reasoning_capability"]
        self.assertIn("expert_scientific_reasoning", reasoning["diagnostic_facets_covered"])
        self.assertIn("long_context_task_reasoning", reasoning["diagnostic_facets_covered"])
        self.assertNotIn("long_context_task_reasoning", reasoning["planned_only_priority_facets"])
        self.assertIn("reasoning_exact_answer_v1", reasoning["known_headline_saturation_risks"])

    def test_missing_scoped_facet_fails_only_structural_claim_coverage(self):
        catalog = deepcopy(load_capability_catalog())
        assistant = next(
            item for item in catalog["surface_score_policies"]
            if item["surface_id"] == "local_assistant_capability"
        )
        assistant["representativeness_policy"]["scoped_claim_facets"].append("unsupported_facet")
        assistant["representativeness_policy"]["priority_facets"].append("unsupported_facet")

        surface = audit_benchmark_adequacy(catalog, surface_id="local_assistant_capability")["surfaces"][0]

        self.assertFalse(surface["scoped_claim_coverage_ready"])
        self.assertEqual(surface["status"], "scoped_claim_coverage_gap")
        self.assertEqual(surface["missing_scoped_claim_facets"], ["unsupported_facet"])

    def test_validation_cannot_hide_a_weighted_component_from_saturation_review(self):
        catalog = deepcopy(load_capability_catalog())
        coding = next(
            item for item in catalog["surface_score_policies"]
            if item["surface_id"] == "local_coding_capability"
        )
        coding["representativeness_policy"]["supporting_check_ids"].remove("coding_static_repair_v1")

        failures = validate_benchmark_adequacy_metadata(catalog)

        self.assertIn(
            "local_coding_capability: supporting_check_ids omits weighted checks: coding_static_repair_v1",
            failures,
        )

    def test_empirical_priority_facet_policy_cannot_be_disabled(self):
        catalog = deepcopy(load_capability_catalog())
        assistant = next(
            item
            for item in catalog["surface_score_policies"]
            if item["surface_id"] == "local_assistant_capability"
        )
        assistant["representativeness_policy"]["empirical_priority_facet_policy"][
            "minimum_observations"
        ] = 0

        failures = validate_benchmark_adequacy_metadata(catalog)

        self.assertIn(
            "local_assistant_capability: empirical priority facet minimum_observations must be a positive integer",
            failures,
        )

        assistant["representativeness_policy"]["empirical_priority_facet_policy"][
            "minimum_observations"
        ] = 8
        assistant["representativeness_policy"]["empirical_priority_facet_policy"][
            "minimum_suite_headroom"
        ] = 0.0

        failures = validate_benchmark_adequacy_metadata(catalog)

        self.assertIn(
            "local_assistant_capability: empirical priority facet minimum_suite_headroom "
            "must be greater than 0 and at most 1",
            failures,
        )

        assistant["representativeness_policy"]["empirical_priority_facet_policy"][
            "ceiling_fraction_confidence_level"
        ] = 1.0
        failures = validate_benchmark_adequacy_metadata(catalog)
        self.assertIn(
            "local_assistant_capability: empirical priority facet "
            "ceiling_fraction_confidence_level must be greater than 0 and less than 1",
            failures,
        )

    def test_empirical_saturation_slice_policy_is_fail_closed(self):
        catalog = deepcopy(load_capability_catalog())
        stateful = next(
            item
            for item in catalog["checks"]
            if item["check_id"] == "stateful_tool_loop_diagnostic_v1"
        )
        stateful["empirical_saturation_slice_policy"]["breakdown_field"] = (
            "undeclared_metrics"
        )
        stateful["empirical_saturation_slice_policy"]["required_slices"] = [
            "noop",
            "noop",
        ]
        stateful["empirical_saturation_slice_policy"]["minimum_cases_per_slice"] = 0
        stateful["higher_is_better"] = False

        failures = validate_benchmark_adequacy_metadata(catalog)

        self.assertIn(
            "stateful_tool_loop_diagnostic_v1: empirical saturation slice "
            "breakdown_field must be declared in score_breakdown_fields",
            failures,
        )
        self.assertIn(
            "stateful_tool_loop_diagnostic_v1: empirical saturation required_slices "
            "must be unique",
            failures,
        )
        self.assertIn(
            "stateful_tool_loop_diagnostic_v1: empirical saturation "
            "minimum_cases_per_slice must be a positive integer",
            failures,
        )
        self.assertIn(
            "stateful_tool_loop_diagnostic_v1: empirical saturation slices require "
            "higher_is_better true",
            failures,
        )

    def test_static_metadata_never_claims_empirical_headroom(self):
        report = audit_benchmark_adequacy(load_capability_catalog())

        for surface in report["surfaces"]:
            self.assertEqual(
                surface["distribution_calibration_status"],
                "provisional_pending_distribution_audit",
            )
        self.assertIn("does not prove", report["interpretation"])

    def test_saturated_diagnostic_blocks_broad_readiness_without_blocking_narrow_scope(self):
        catalog = deepcopy(load_capability_catalog())
        assistant = next(
            item for item in catalog["surface_score_policies"]
            if item["surface_id"] == "local_assistant_capability"
        )
        assistant_policy = assistant["representativeness_policy"]
        assistant_policy["priority_facets"] = list(assistant_policy["scoped_claim_facets"]) + [
            "multi_turn_state_retention"
        ]
        assistant_policy["planned_check_ids"] = []
        assistant_policy["minimum_refreshable_priority_facets"] = 0

        surface = audit_benchmark_adequacy(catalog, surface_id="local_assistant_capability")["surfaces"][0]

        self.assertTrue(surface["scoped_claim_coverage_ready"])
        self.assertEqual(surface["missing_priority_facets"], [])
        self.assertEqual(surface["known_headline_saturation_risks"], [])
        self.assertEqual(surface["known_diagnostic_saturation_risks"], ["multiturn_chat_memory_v1"])
        self.assertFalse(surface["broad_surface_coverage_ready"])


if __name__ == "__main__":
    unittest.main()
