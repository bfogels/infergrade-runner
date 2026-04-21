import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.benchmark_catalog import (
    benchmark_scope_summary_for_selection,
    capability_benchmark_ids_for_request,
    fidelity_enabled_for_request,
    load_capability_catalog,
    normalize_request_selection,
)
from infergrade.models import RunRequest


class BenchmarkCatalogTests(unittest.TestCase):
    def test_capability_catalog_exposes_suites_groups_and_checks(self):
        catalog = load_capability_catalog()
        self.assertGreaterEqual(len(catalog["suites"]), 3)
        self.assertGreaterEqual(len(catalog["benchmark_groups"]), 5)
        self.assertGreaterEqual(len(catalog["checks"]), 6)
        self.assertIn("metadata_ordering", catalog)
        self.assertEqual(catalog["metadata_source_defaults"]["duration"], "estimated")
        self.assertEqual(catalog["benchmark_scopes"][0]["scope_id"], "decision")
        for check in catalog["checks"]:
            self.assertIn(check["suite_scope"], {"decision", "reference"})
            self.assertTrue(check["expected_duration_band"])
            self.assertTrue(check["execution_pattern"])

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
        self.assertEqual(decision["effort_level"], "balanced")
        self.assertFalse(decision["reference_checks_included"])
        self.assertEqual(decision["metadata_sources"]["duration"], "estimated")
        self.assertEqual(decision["metadata_sources"]["failure_rate"], "unknown")
        self.assertEqual(decision["metadata_confidence"], "unknown")

        reference = benchmark_scope_summary_for_selection(["interactive_chat_v1", "perplexity_reference_v1"])
        self.assertEqual(reference["scope"], "reference")
        self.assertEqual(reference["scope_label"], "Reference suite")
        self.assertTrue(reference["reference_checks_included"])
        self.assertIn("throughput_oriented_offline_suite", reference["execution_patterns"])

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
