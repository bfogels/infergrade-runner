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
        self.assertEqual(details["score_version"], "local_assistant_score_v1")
        self.assertEqual(details["score_method"], "weighted_primary_metric_v1")
        self.assertEqual(details["score"], 0.462108)
        self.assertEqual(details["coverage"]["coverage_fraction"], 1.0)
        self.assertEqual(
            {item["benchmark_id"]: item["weight"] for item in details["components"]},
            {"ifeval": 0.75, "multiturn_chat_memory_v1": 0.25},
        )

    def test_thin_microcheck_is_observed_but_not_headline_ready(self):
        details = score_for_use_case(
            "general_assistant",
            {"multiturn_chat_memory_v1": 1.0},
        )

        self.assertFalse(details["score_ready"])
        self.assertEqual(details["score"], None)
        self.assertEqual(details["observed_weighted_score"], 1.0)
        self.assertEqual(details["reason"], "insufficient_weighted_coverage")
        self.assertEqual(details["coverage"]["coverage_fraction"], 0.25)

    def test_auxiliary_reasoning_check_does_not_become_assistant_score(self):
        details = score_for_use_case(
            "general_assistant",
            {"mmlu_pro_reference_v1": 0.9},
        )

        self.assertEqual(details["surface_id"], "local_assistant_capability")
        self.assertEqual(details["score"], None)
        self.assertEqual(details["reason"], "no_scored_components")


if __name__ == "__main__":
    unittest.main()
