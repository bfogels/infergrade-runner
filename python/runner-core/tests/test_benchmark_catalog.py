import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.benchmark_catalog import (
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


if __name__ == "__main__":
    unittest.main()
