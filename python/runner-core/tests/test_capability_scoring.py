import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.capability_scoring import score_for_use_case


class CapabilityScoringTests(unittest.TestCase):
    def test_assistant_score_uses_versioned_runner_weights(self):
        details = score_for_use_case(
            "general_assistant",
            {"ifeval": 0.28281, "multiturn_chat_memory_v1": 1.0},
        )

        self.assertTrue(details["score_ready"])
        self.assertEqual(details["score_version"], "local_assistant_score_v2")
        self.assertEqual(details["score_method"], "weighted_primary_metric_v2")
        self.assertEqual(details["score"], 0.462108)
        self.assertEqual(details["coverage"]["coverage_fraction"], 1.0)
        self.assertEqual(
            {item["benchmark_id"]: item["weight"] for item in details["components"]},
            {"ifeval": 0.75, "multiturn_chat_memory_v1": 0.25},
        )
        self.assertEqual(details["failed_gates"], [])
        self.assertTrue(details["robustness"]["dominant_component"])
        self.assertEqual(details["robustness"]["dominant_benchmark_ids"], ["ifeval"])
        self.assertEqual(details["robustness"]["max_absolute_delta"], 0.537892)
        self.assertEqual(details["confidence_basis"]["calibration_status"], "not_psychometrically_calibrated")
        self.assertEqual(details["confidence_basis"]["label"], "multi_component_dominant")

    def test_thin_microcheck_is_observed_but_not_headline_ready(self):
        details = score_for_use_case(
            "general_assistant",
            {"multiturn_chat_memory_v1": 1.0},
        )

        self.assertFalse(details["score_ready"])
        self.assertEqual(details["score"], None)
        self.assertEqual(details["observed_weighted_score"], 1.0)
        self.assertEqual(details["reason"], "insufficient_weighted_coverage")
        self.assertIn("insufficient_scored_components", details["failed_gates"])
        self.assertIn("insufficient_score_dimensions", details["failed_gates"])
        self.assertIn("component_influence_above_limit", details["failed_gates"])
        self.assertEqual(details["coverage"]["coverage_fraction"], 0.25)

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
