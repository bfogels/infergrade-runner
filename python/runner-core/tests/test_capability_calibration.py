import unittest

from infergrade.capability_calibration import (
    audit_capability_observations,
    extract_calibration_observations,
    policy_for_score_version,
)
from infergrade.benchmark_catalog import load_capability_catalog


class CapabilityCalibrationTests(unittest.TestCase):
    def test_each_task_surface_owns_an_independent_distribution_policy(self):
        catalog = load_capability_catalog()

        assistant = policy_for_score_version("local_assistant_score_v4", catalog=catalog)
        coding = policy_for_score_version("local_coding_score_v2", catalog=catalog)
        reasoning = policy_for_score_version("local_reasoning_score_v2", catalog=catalog)

        self.assertEqual(assistant["policy_id"], "capability_headroom_gate_v2")
        self.assertEqual(coding["policy_id"], "coding_capability_headroom_gate_v1")
        self.assertEqual(reasoning["policy_id"], "reasoning_capability_headroom_gate_v1")
        for policy in (assistant, coding, reasoning):
            self.assertEqual(policy["minimum_observations"], 20)
            self.assertEqual(policy["minimum_unique_setups"], 8)
            self.assertEqual(policy["minimum_replicated_setups"], 4)
            self.assertEqual(policy["maximum_suite_ceiling_fraction"], 0.2)
            self.assertEqual(policy["minimum_suite_headroom"], 0.1)
            self.assertEqual(policy["minimum_headline_component_observations"], 8)
            self.assertEqual(policy["maximum_headline_component_ceiling_fraction"], 0.2)
            self.assertEqual(policy["minimum_headline_component_headroom"], 0.1)

    def test_audit_blocks_small_or_saturated_corpus_without_rescaling_scores(self):
        observations = [
            {"score_version": "local_assistant_score_v4", "score": 1.0, "model_family": "A", "parameter_band": "under_3b"},
            {"score_version": "local_assistant_score_v4", "score": 1.0, "model_family": "A", "parameter_band": "under_3b"},
        ]
        report = audit_capability_observations(observations, "local_assistant_score_v4")
        self.assertEqual(report["status"], "insufficient_calibration")
        self.assertFalse(report["headline_ready"])
        self.assertEqual(report["metrics"]["maximum"], 1.0)
        self.assertIn("suite_ceiling_fraction_above_limit", report["blockers"])

    def test_audit_passes_diverse_distribution_with_headroom(self):
        scores = [0.12, 0.18, 0.24, 0.31, 0.37, 0.43, 0.49, 0.54, 0.59, 0.64,
                  0.15, 0.22, 0.29, 0.35, 0.41, 0.47, 0.52, 0.57, 0.62, 0.68]
        observations = [
            {
                "score_version": "local_assistant_score_v4",
                "score": score,
                "model_family": "family-%d" % (index % 5),
                "parameter_band": ["under_3b", "3b_to_under_8b", "8b_to_under_20b"][index % 3],
            }
            for index, score in enumerate(scores)
        ]
        report = audit_capability_observations(observations, "local_assistant_score_v4")
        self.assertEqual(report["status"], "calibrated_headroom")
        self.assertTrue(report["headline_ready"])
        self.assertEqual(report["blockers"], [])

    def test_audit_blocks_near_ceiling_distribution_before_literal_saturation(self):
        catalog = load_capability_catalog()
        policy = policy_for_score_version("local_assistant_score_v4", catalog=catalog)
        policy.pop("minimum_current_generation_fraction")
        policy.pop("minimum_headline_component_observations")
        scores = [0.95] + [0.2 + index / 100.0 for index in range(19)]
        observations = [
            {
                "score_version": "local_assistant_score_v4",
                "score": score,
                "model_family": "family-%d" % (index % 5),
                "parameter_band": ["under_3b", "3b_to_under_8b", "8b_to_under_20b"][index % 3],
                "model_identities": ["model-%d" % (index % 10)],
                "quantization_scheme": "q4_k_m",
            }
            for index, score in enumerate(scores)
        ]

        report = audit_capability_observations(
            observations,
            "local_assistant_score_v4",
            policy=policy,
            catalog=catalog,
        )

        self.assertEqual(report["metrics"]["suite_ceiling_count"], 0)
        self.assertEqual(report["metrics"]["headroom_to_suite_ceiling"], 0.05)
        self.assertIn("insufficient_suite_headroom", report["blockers"])

    def test_extracts_raw_attainment_from_result_record(self):
        observations = extract_calibration_observations(
            [{
                "result_id": "result-1",
                "capability": {"capability_score_details": {
                    "score_version": "local_assistant_score_v4",
                    "surface_id": "local_assistant_capability",
                    "raw_attainment": 0.625,
                    "score_ready": True,
                }},
                "model_id": "Qwen/Qwen3.5-9B",
                "ontology": {
                    "model_family": {"family_name": "Qwen3.5", "parameter_scale": "9B"},
                    "checkpoint": {"checkpoint_name": "Qwen3.5-9B"},
                    "quantization": {"quantization_scheme": "q4_k_m"},
                },
            }]
        )
        self.assertEqual(observations[0]["score"], 0.625)
        self.assertEqual(observations[0]["parameter_band"], "8b_to_under_20b")
        self.assertIn("qwen359b", observations[0]["model_identities"])
        self.assertEqual(observations[0]["quantization_scheme"], "q4_k_m")

    def test_extracts_completed_component_scores_from_full_and_compact_results(self):
        component = {
            "benchmark_id": "reasoning_exact_answer_v1",
            "component_score": 1.0,
            "status": "completed",
        }
        documents = [
            {
                "result_id": "full-result",
                "capability": {
                    "capability_score_details": {
                        "score_version": "local_reasoning_score_v2",
                        "surface_id": "local_reasoning_capability",
                        "raw_attainment": 0.68,
                        "score_ready": True,
                    },
                    "capability_component_reports": [component],
                },
            },
            {
                "result_id": "compact-result",
                "capability_score_version": "local_reasoning_score_v2",
                "capability_score_surface_id": "local_reasoning_capability",
                "capability_score": 0.64,
                "capability_score_ready": True,
                "capability_component_reports": [component],
            },
        ]

        observations = extract_calibration_observations(documents, score_version="local_reasoning_score_v2")

        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0]["components"], [{"benchmark_id": "reasoning_exact_answer_v1", "score": 1.0}])
        self.assertEqual(observations[1]["components"], [{"benchmark_id": "reasoning_exact_answer_v1", "score": 1.0}])

    def test_duplicate_component_reports_cannot_inflate_calibration_counts(self):
        observations = extract_calibration_observations([{
            "result_id": "duplicate-components",
            "capability_score_version": "local_reasoning_score_v2",
            "capability_score": 0.6,
            "capability_score_ready": True,
            "capability_component_reports": [
                {"benchmark_id": "reasoning_exact_answer_v1", "component_score": 1.0, "status": "completed"},
                {"benchmark_id": "reasoning_exact_answer_v1", "component_score": 0.0, "status": "completed"},
            ],
        }])

        self.assertEqual(observations[0]["components"], [])

    def test_weighted_component_saturation_blocks_headline_even_with_composite_headroom(self):
        catalog = load_capability_catalog()
        policy = policy_for_score_version("local_reasoning_score_v2", catalog=catalog)
        policy.pop("minimum_current_generation_fraction")
        observations = []
        for index in range(20):
            observations.append({
                "score_version": "local_reasoning_score_v2",
                "surface_id": "local_reasoning_capability",
                "score": 0.3 + index / 100.0,
                "model_family": "family-%d" % (index % 5),
                "parameter_band": ["under_3b", "3b_to_under_8b", "8b_to_under_20b"][index % 3],
                "model_identities": ["model-%d" % (index % 10)],
                "quantization_scheme": "q4_k_m",
                "components": [
                    {"benchmark_id": "mmlu_pro_reference_v1", "score": 0.2 + index / 100.0},
                    {"benchmark_id": "reasoning_exact_answer_v1", "score": 1.0},
                ],
            })

        report = audit_capability_observations(
            observations,
            "local_reasoning_score_v2",
            policy=policy,
            catalog=catalog,
        )

        exact = report["metrics"]["headline_components"]["reasoning_exact_answer_v1"]
        self.assertEqual(exact["observation_count"], 20)
        self.assertEqual(exact["suite_ceiling_fraction"], 1.0)
        self.assertEqual(exact["headroom_to_suite_ceiling"], 0.0)
        self.assertIn(
            "headline_component_ceiling_fraction_above_limit:reasoning_exact_answer_v1",
            report["blockers"],
        )
        self.assertEqual(report["status"], "saturation_or_concentration_risk")
        self.assertFalse(report["headline_ready"])

    def test_thin_weighted_component_is_reported_as_insufficient_not_saturated(self):
        catalog = load_capability_catalog()
        observations = [
            {
                "score_version": "local_coding_score_v2",
                "surface_id": "local_coding_capability",
                "score": 0.4,
                "model_family": "family-%d" % (index % 5),
                "parameter_band": ["under_3b", "3b_to_under_8b", "8b_to_under_20b"][index % 3],
                "model_identities": ["model-%d" % (index % 10)],
                "quantization_scheme": "q4_k_m",
                "components": [
                    {"benchmark_id": "evalplus_humaneval", "score": 0.5},
                    {"benchmark_id": "evalplus_mbpp", "score": 0.45},
                ] + ([{"benchmark_id": "coding_static_repair_v1", "score": 1.0}] if index < 4 else []),
            }
            for index in range(20)
        ]

        report = audit_capability_observations(
            observations,
            "local_coding_score_v2",
            policy=policy_for_score_version("local_coding_score_v2", catalog=catalog),
            catalog=catalog,
        )

        static_repair = report["metrics"]["headline_components"]["coding_static_repair_v1"]
        self.assertEqual(static_repair["observation_count"], 4)
        self.assertEqual(static_repair["suite_ceiling_fraction"], 1.0)
        self.assertIn(
            "insufficient_headline_component_observations:coding_static_repair_v1",
            report["blockers"],
        )
        self.assertNotIn(
            "headline_component_ceiling_fraction_above_limit:coding_static_repair_v1",
            report["blockers"],
        )

    def test_runner_policy_blocks_legacy_repeat_farming(self):
        catalog = load_capability_catalog()
        observations = [
            {
                "score_version": "local_assistant_score_v4",
                "score": 0.1 + index / 100.0,
                "model_family": "Qwen2.5",
                "parameter_band": "3b_to_under_8b",
                "model_identities": ["qwen257binstruct"],
                "quantization_scheme": "q4_k_m",
            }
            for index in range(20)
        ]

        report = audit_capability_observations(
            observations,
            "local_assistant_score_v4",
            policy=policy_for_score_version("local_assistant_score_v4", catalog=catalog),
            catalog=catalog,
        )

        self.assertEqual(report["metrics"]["unique_setup_count"], 1)
        self.assertEqual(report["metrics"]["replicated_setup_count"], 1)
        self.assertEqual(report["metrics"]["current_generation_fraction"], 0.0)
        self.assertIn("insufficient_unique_setup_count", report["blockers"])
        self.assertIn("insufficient_replicated_setup_count", report["blockers"])
        self.assertIn("insufficient_current_generation_fraction", report["blockers"])
        self.assertIn("single_setup_fraction_above_limit", report["blockers"])

    def test_export_file_keeps_multiple_result_ids(self):
        documents = []
        for index, score in enumerate((0.25, 0.5), start=1):
            documents.append({
                "_source": "/tmp/results-export.json",
                "result_id": "result-%d" % index,
                "capability": {"capability_score_details": {
                    "score_version": "local_assistant_score_v4",
                    "score_ready": True,
                    "raw_attainment": score,
                }},
            })

        observations = extract_calibration_observations(documents, score_version="local_assistant_score_v4")

        self.assertEqual([item["score"] for item in observations], [0.25, 0.5])

    def test_extracts_flat_normalized_result_brief(self):
        observations = extract_calibration_observations([{
            "result_id": "brief-1",
            "capability_score_version": "local_assistant_score_v4",
            "capability_score": 0.42,
            "capability_score_ready": True,
            "model_id": "Qwen/Qwen3.5-9B",
            "model_family": "Qwen3.5",
            "parameter_scale": "9B",
            "checkpoint_name": "Qwen3.5-9B",
            "quantization_scheme": "q4_k_m",
        }])

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["score"], 0.42)
        self.assertEqual(observations[0]["quantization_scheme"], "q4_k_m")

    def test_extracts_component_observation_without_mislabeling_it_as_full_score(self):
        observations = extract_calibration_observations(
            [{
                "artifact_kind": "capability_run",
                "capability_run_id": "caprun-1",
                "protocol": {
                    "task_version": "assistant_compositional_instruction_v2",
                    "fixture_revision": "2026-07-assistant-compositional-v2",
                },
                "summary": {"score": 0.458333, "state": "scored"},
                "tasks": [{} for _ in range(24)],
                "subject": {"model": {"model": "Qwen/Qwen3.5-9B"}},
                "evidence": {"surface": "local_assistant_capability"},
            }],
            benchmark_id="assistant_compositional_instruction_v2",
        )

        self.assertEqual(observations[0]["benchmark_id"], "assistant_compositional_instruction_v2")
        self.assertEqual(observations[0]["task_count"], 24)
        self.assertEqual(observations[0]["score_version"], "benchmark:assistant_compositional_instruction_v2:2026-07-assistant-compositional-v2")


if __name__ == "__main__":
    unittest.main()
