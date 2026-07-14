import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.capability_scoring import score_for_use_case


class CapabilityScoringTests(unittest.TestCase):
    def test_assistant_score_uses_versioned_runner_weights(self):
        details = score_for_use_case(
            "general_assistant",
            {
                "ifeval": 0.28281,
                "assistant_compositional_instruction_v2": 0.75,
                "multiturn_chat_memory_v1": 1.0,
            },
            benchmark_tier="standard",
        )

        self.assertTrue(details["score_ready"])
        self.assertEqual(details["score_version"], "local_assistant_score_v4")
        self.assertEqual(details["score_method"], "weighted_benchmark_attainment_v4")
        self.assertEqual(details["protocol_version"], "3.1")
        self.assertEqual(details["protocol_label"], "Capability protocol v3.1")
        self.assertEqual(details["score"], 0.539764)
        self.assertEqual(details["coverage"]["coverage_fraction"], 1.0)
        self.assertEqual(
            {item["benchmark_id"]: item["weight"] for item in details["components"]},
            {"ifeval": 0.45, "assistant_compositional_instruction_v2": 0.55},
        )
        self.assertEqual(details["scale_interpretation"], "benchmark_attainment_index")
        self.assertFalse(details["ceiling"]["reached"])
        self.assertEqual(details["diagnostic_components"][0]["benchmark_id"], "multiturn_chat_memory_v1")
        self.assertEqual(details["diagnostic_components"][0]["score"], 1.0)
        self.assertEqual(details["diagnostic_components"][0]["discrimination_status"], "empirically_saturated")
        self.assertEqual(details["failed_gates"], [])
        self.assertFalse(details["robustness"]["dominant_component"])
        self.assertEqual(details["robustness"]["dominant_benchmark_ids"], [])
        self.assertEqual(details["robustness"]["max_absolute_delta"], 0.256954)
        self.assertEqual(details["confidence_basis"]["calibration_status"], "not_psychometrically_calibrated")
        self.assertEqual(details["confidence_basis"]["label"], "multi_component_complete_coverage")

    def test_thin_microcheck_is_observed_but_not_headline_ready(self):
        details = score_for_use_case(
            "general_assistant",
            {"multiturn_chat_memory_v1": 1.0},
        )

        self.assertFalse(details["score_ready"])
        self.assertEqual(details["score"], None)
        self.assertEqual(details["observed_weighted_score"], None)
        self.assertEqual(details["reason"], "no_scored_components")
        self.assertIn("insufficient_scored_components", details["failed_gates"])
        self.assertIn("insufficient_score_dimensions", details["failed_gates"])
        self.assertEqual(details["coverage"]["coverage_fraction"], 0.0)
        self.assertEqual(details["diagnostic_components"][0]["score"], 1.0)

    def test_suite_ceiling_is_labeled_as_attainment_not_perfect_capability(self):
        details = score_for_use_case(
            "general_assistant",
            {"ifeval": 1.0, "assistant_compositional_instruction_v2": 1.0},
            benchmark_tier="standard",
        )

        self.assertTrue(details["score_ready"])
        self.assertEqual(details["score"], 1.0)
        self.assertTrue(details["ceiling"]["reached"])
        self.assertEqual(details["ceiling"]["label"], "Suite ceiling reached")
        self.assertIn("not proof of perfect model capability", details["ceiling"]["interpretation"])

    def test_assistant_canary_depth_cannot_publish_a_headline_index(self):
        details = score_for_use_case(
            "general_assistant",
            {"ifeval": 1.0, "assistant_compositional_instruction_v2": 1.0},
            benchmark_tier="canary",
        )

        self.assertFalse(details["score_ready"])
        self.assertIsNone(details["score"])
        self.assertIn("insufficient_benchmark_depth", details["failed_gates"])
        self.assertEqual(details["eligibility"]["minimum_benchmark_tier"], "standard")
        self.assertFalse(details["eligibility"]["benchmark_depth_ready"])

    def test_auxiliary_reasoning_check_does_not_become_assistant_score(self):
        details = score_for_use_case(
            "general_assistant",
            {"mmlu_pro_reference_v1": 0.9},
        )

        self.assertEqual(details["surface_id"], "local_assistant_capability")
        self.assertEqual(details["score"], None)
        self.assertEqual(details["reason"], "no_scored_components")

    def test_reasoning_use_case_scores_the_reasoning_surface(self):
        details = score_for_use_case(
            "reasoning",
            {"reasoning_exact_answer_v1": 1.0, "mmlu_pro_reference_v1": 0.44},
        )

        self.assertTrue(details["score_ready"])
        self.assertEqual(details["surface_id"], "local_reasoning_capability")
        self.assertEqual(details["score_version"], "local_reasoning_score_v2")
        self.assertEqual(details["coverage"]["coverage_fraction"], 1.0)

    def test_two_distinct_components_and_dimensions_are_required_even_when_weight_coverage_passes(self):
        details = score_for_use_case("agentic_coding", {"evalplus_humaneval": 0.8})

        self.assertFalse(details["score_ready"])
        self.assertEqual(details["observed_weighted_score"], 0.8)
        self.assertIn("insufficient_scored_components", details["failed_gates"])
        self.assertIn("insufficient_score_dimensions", details["failed_gates"])

    def test_coding_v2_exposes_deterministic_leave_one_out_sensitivity(self):
        details = score_for_use_case(
            "agentic_coding",
            {"evalplus_humaneval": 0.8, "evalplus_mbpp": 0.6},
        )

        self.assertTrue(details["score_ready"])
        self.assertEqual(details["score_version"], "local_coding_score_v2")
        self.assertEqual(details["score"], 0.729412)
        self.assertEqual(details["robustness"]["max_absolute_delta"], 0.129412)
        self.assertFalse(details["robustness"]["dominant_component"])
        self.assertEqual(details["confidence_basis"]["label"], "multi_component_partial_coverage")


if __name__ == "__main__":
    unittest.main()
