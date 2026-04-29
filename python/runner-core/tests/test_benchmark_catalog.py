import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.benchmark_catalog import (
    benchmark_scope_summary_for_selection,
    capability_coverage_guidance_for_selection,
    capability_benchmark_ids_for_request,
    fidelity_enabled_for_request,
    load_capability_catalog,
    normalize_request_selection,
    selection_metadata_for_request,
)
from infergrade.models import RunRequest


class BenchmarkCatalogTests(unittest.TestCase):
    def test_capability_catalog_exposes_suites_groups_and_checks(self):
        catalog = load_capability_catalog()
        self.assertGreaterEqual(len(catalog["suites"]), 3)
        self.assertGreaterEqual(len(catalog["benchmark_groups"]), 5)
        self.assertGreaterEqual(len(catalog["checks"]), 6)
        self.assertIn("metadata_ordering", catalog)
        self.assertTrue(catalog["score_policies"])
        self.assertEqual(catalog["metadata_source_defaults"]["duration"], "estimated")
        self.assertEqual(catalog["benchmark_scopes"][0]["scope_id"], "decision")
        for check in catalog["checks"]:
            self.assertIn(check["suite_scope"], {"decision", "reference"})
            self.assertTrue(check["expected_duration_band"])
            self.assertTrue(check["execution_pattern"])
            self.assertTrue(check["score_dimension"])
            self.assertTrue(check["primary_score_metric"])
            self.assertIn("higher_is_better", check)
            self.assertIn("score_floor", check)
            self.assertIn("primary_score_weight", check)
            self.assertTrue(check["score_policy_id"])
        self.assertTrue(catalog["planned_benchmark_candidates"])

    def test_normalize_request_selection_derives_breadth_from_legacy_lane(self):
        request = RunRequest(model="Qwen/Qwen2.5-7B-Instruct", backend="llama.cpp", tier="standard", use_case="general_assistant")
        normalize_request_selection(request)
        self.assertIn("chat_instruction_following", request.capability_suite_ids)
        self.assertIn("instruction_following", request.benchmark_group_ids)
        self.assertIn("ifeval", request.benchmark_check_ids)
        self.assertIn("interactive_chat_v1", request.deployment_profiles)

    def test_capability_and_fidelity_helpers_follow_explicit_check_selection(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            capability_suite_ids=["coding_code_editing", "quant_fidelity"],
            benchmark_group_ids=["coding_core", "quant_fidelity"],
            benchmark_check_ids=["evalplus_humaneval", "perplexity_reference_v1"],
        )
        normalize_request_selection(request)
        self.assertEqual(capability_benchmark_ids_for_request(request), ["evalplus_humaneval"])
        self.assertTrue(fidelity_enabled_for_request(request))
        self.assertEqual(request.tier, "standard")

    def test_benchmark_scope_summary_distinguishes_decision_and_reference_sets(self):
        decision = benchmark_scope_summary_for_selection(["ifeval", "interactive_chat_v1"])
        self.assertEqual(decision["scope"], "decision")
        self.assertIn("recommended short local path", decision["selection_guidance"])
        self.assertEqual(decision["effort_level"], "balanced")
        self.assertFalse(decision["reference_checks_included"])
        self.assertEqual(decision["metadata_sources"]["duration"], "estimated")
        self.assertEqual(decision["metadata_sources"]["failure_rate"], "unknown")
        self.assertEqual(decision["metadata_confidence"], "unknown")

        reference = benchmark_scope_summary_for_selection(["interactive_chat_v1", "perplexity_reference_v1"])
        self.assertEqual(reference["scope"], "reference")
        self.assertEqual(reference["scope_label"], "Reference suite")
        self.assertIn("deeper evidence", reference["selection_guidance"])
        self.assertTrue(reference["reference_checks_included"])
        self.assertIn("throughput_oriented_offline_suite", reference["execution_patterns"])

    def test_capability_coverage_guidance_marks_unselected_evidence_as_gap(self):
        guidance = capability_coverage_guidance_for_selection(["interactive_chat_v1"])
        missing = {item["evidence_kind"]: item for item in guidance["missing_core_evidence"]}
        self.assertEqual(missing["capability"]["state"], "not_selected")
        self.assertIn("not a failed benchmark", missing["capability"]["message"])
        self.assertIn("perplexity_reference_v1", guidance["available_reference_check_ids"])
        self.assertTrue(guidance["planned_benchmark_candidates"])
        self.assertTrue(any(action["action"] == "add_capability_check" for action in guidance["next_actions"]))

    def test_selection_metadata_includes_scope_and_coverage_guidance(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            benchmark_check_ids=["ifeval", "interactive_chat_v1"],
        )
        metadata = selection_metadata_for_request(request)
        self.assertEqual(metadata["benchmark_scope"]["scope"], "decision")
        self.assertEqual(metadata["capability_coverage_guidance"]["selected_decision_check_ids"], ["ifeval", "interactive_chat_v1"])
        self.assertIn("status", metadata["benchmark_checks"][0])
        score_dimensions = {item["check_id"]: item["score_dimension"] for item in metadata["benchmark_checks"]}
        self.assertEqual(score_dimensions["ifeval"], "instruction_following")
        self.assertEqual(score_dimensions["interactive_chat_v1"], "interactive_latency")
        interactive = next(item for item in metadata["benchmark_checks"] if item["check_id"] == "interactive_chat_v1")
        self.assertFalse(interactive["higher_is_better"])
        self.assertEqual(interactive["primary_score_weight"], 0.0)
        self.assertIn("time_to_first_token_ms", interactive["score_breakdown_fields"])
        policy_ids = [item["score_policy_id"] for item in metadata["score_policies"]]
        self.assertEqual(policy_ids, ["instruction_following_primary_accuracy_v1", "deployment_profile_metrics_v1"])

    def test_benchmark_scope_summary_empty_selection_uses_computed_confidence(self):
        summary = benchmark_scope_summary_for_selection([])
        self.assertEqual(summary["metadata_sources"]["failure_rate"], "unknown")
        self.assertEqual(summary["metadata_confidence"], "unknown")

    def test_benchmark_scope_summary_treats_missing_metadata_as_default_source(self):
        catalog = load_capability_catalog()
        custom_catalog = dict(catalog)
        custom_catalog["checks"] = [dict(item) for item in catalog["checks"]]
        for check in custom_catalog["checks"]:
            if check["check_id"] == "interactive_chat_v1":
                check["duration_metadata_source"] = "observed"
            if check["check_id"] == "evalplus_mbpp":
                check.pop("duration_metadata_source", None)
        summary = benchmark_scope_summary_for_selection(["interactive_chat_v1", "evalplus_mbpp"], custom_catalog)
        self.assertEqual(summary["metadata_sources"]["duration"], "mixed")

    def test_benchmark_scope_summary_ignores_calibration_status_for_observed_confidence(self):
        catalog = load_capability_catalog()
        custom_catalog = dict(catalog)
        custom_catalog["checks"] = [dict(item) for item in catalog["checks"]]
        for check in custom_catalog["checks"]:
            if check["check_id"] in {"interactive_chat_v1", "evalplus_mbpp"}:
                check["duration_metadata_source"] = "observed"
                check["token_volume_metadata_source"] = "observed"
                check["failure_rate_metadata_source"] = "observed"
        summary = benchmark_scope_summary_for_selection(["interactive_chat_v1", "evalplus_mbpp"], custom_catalog)
        self.assertEqual(summary["metadata_confidence"], "observed")

    def test_benchmark_scope_summary_uses_catalog_declared_ordering(self):
        catalog = load_capability_catalog()
        custom_catalog = dict(catalog)
        custom_catalog["metadata_ordering"] = {
            **dict(catalog.get("metadata_ordering") or {}),
            "expected_duration_band": ["25-60 min", "5-15 min", "10-25 min", "10-30 min", "15-45 min", "1-5 min"],
        }

        summary = benchmark_scope_summary_for_selection(["interactive_chat_v1", "evalplus_mbpp"], custom_catalog)

        self.assertEqual(summary["expected_duration_band"], "1-5 min")


if __name__ == "__main__":
    unittest.main()
