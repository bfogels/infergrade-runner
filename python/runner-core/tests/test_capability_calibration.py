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
            self.assertEqual(policy["minimum_independently_replicated_setups"], 4)
            self.assertEqual(policy["maximum_suite_ceiling_fraction"], 0.2)
            self.assertEqual(policy["minimum_suite_headroom"], 0.1)
            self.assertEqual(policy["minimum_headline_component_observations"], 8)
            self.assertEqual(policy["minimum_headline_component_model_families"], 3)
            self.assertEqual(policy["minimum_headline_component_parameter_bands"], 2)
            self.assertEqual(
                policy["minimum_headline_component_independently_replicated_setups"],
                2,
            )
            self.assertEqual(policy["maximum_headline_component_ceiling_fraction"], 0.2)
            self.assertEqual(policy["minimum_headline_component_headroom"], 0.1)
            self.assertEqual(policy["minimum_headroom_challenge_observations"], 2)
            self.assertEqual(policy["minimum_headroom_challenge_model_families"], 1)
            self.assertEqual(
                policy["minimum_headroom_challenge_independently_replicated_setups"],
                1,
            )

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

    def test_curated_headroom_challenge_is_required_after_generic_diversity_passes(self):
        policy = {
            "minimum_observations": 20,
            "minimum_model_families": 5,
            "minimum_parameter_bands": 3,
            "minimum_distinct_scores": 6,
            "minimum_unique_setups": 8,
            "minimum_replicated_setups": 4,
            "minimum_independently_replicated_setups": 4,
            "minimum_current_generation_fraction": 0.75,
            "minimum_headroom_challenge_observations": 2,
            "minimum_headroom_challenge_model_families": 1,
            "minimum_headroom_challenge_independently_replicated_setups": 1,
            "maximum_suite_ceiling_fraction": 0.2,
            "minimum_suite_headroom": 0.1,
            "maximum_largest_family_fraction": 0.4,
            "maximum_single_setup_fraction": 0.25,
        }
        bands = ["under_3b", "3b_to_under_8b", "8b_to_under_20b"]
        scale_by_band = {
            "under_3b": "1B",
            "3b_to_under_8b": "4B",
            "8b_to_under_20b": "9B",
        }
        priorities = []
        observations = []
        for setup_index in range(10):
            band = bands[setup_index % len(bands)]
            model_id = "models/current-%d-%s" % (setup_index, scale_by_band[band])
            priorities.append({
                "model_id": model_id,
                "parameter_scale": scale_by_band[band],
                "target_quants": ["q4_k_m"],
                "model_freshness": "current_generation",
                "calibration_campaign_eligible": True,
            })
            for group_index in range(2):
                observations.append({
                    "score_version": "local_assistant_score_v4",
                    "score": 0.2 + setup_index / 25.0 + group_index / 100.0,
                    "model_family": "family-%d" % (setup_index % 5),
                    "parameter_band": band,
                    "model_identities": [
                        "current%d%s" % (
                            setup_index,
                            scale_by_band[band].lower(),
                        )
                    ],
                    "quantization_scheme": "q4_k_m",
                    "evidence_group_id": "group-%d" % group_index,
                    "evidence_group_verified": True,
                })
        priorities.append({
            "model_id": "Qwen/Qwen3.6-27B",
            "parameter_scale": "27B",
            "target_quants": ["q3_k_m"],
            "model_freshness": "current_generation",
            "calibration_campaign_eligible": True,
            "headroom_challenge_eligible": True,
        })
        catalog = {"coverage_expansion_priorities": priorities}

        generic_only = audit_capability_observations(
            observations,
            "local_assistant_score_v4",
            policy=policy,
            catalog=catalog,
        )

        self.assertEqual(generic_only["metrics"]["model_family_count"], 5)
        self.assertEqual(generic_only["metrics"]["parameter_band_count"], 3)
        self.assertEqual(generic_only["metrics"]["current_generation_fraction"], 1.0)
        self.assertEqual(generic_only["metrics"]["independently_replicated_setup_count"], 10)
        self.assertEqual(generic_only["metrics"]["headroom_challenge_observation_count"], 0)
        self.assertEqual(generic_only["metrics"]["headroom_challenge_model_family_count"], 0)
        self.assertIn("insufficient_headroom_challenge_observation_count", generic_only["blockers"])
        self.assertIn("insufficient_headroom_challenge_model_family_count", generic_only["blockers"])
        self.assertIn(
            "insufficient_headroom_challenge_independently_replicated_setup_count",
            generic_only["blockers"],
        )
        self.assertEqual(len(generic_only["blockers"]), 3)

        challenge = [
            {
                "score_version": "local_assistant_score_v4",
                "score": 0.61 + index / 100.0,
                "model_family": "Qwen3.6",
                "parameter_band": "20b_to_under_40b",
                "model_identities": ["qwen3627b"],
                "quantization_scheme": "q3_k_m",
                "evidence_group_id": "challenge-source-%d" % index,
                "evidence_group_verified": True,
            }
            for index in range(2)
        ]
        challenged = audit_capability_observations(
            observations + challenge,
            "local_assistant_score_v4",
            policy=policy,
            catalog=catalog,
        )

        self.assertEqual(challenged["metrics"]["headroom_challenge_observation_count"], 2)
        self.assertEqual(challenged["metrics"]["headroom_challenge_model_family_count"], 1)
        self.assertEqual(
            challenged["metrics"]["headroom_challenge_independently_replicated_setup_count"],
            1,
        )
        self.assertTrue(challenged["headline_ready"])
        self.assertEqual(challenged["blockers"], [])

    def test_headroom_challenge_requires_every_weighted_component(self):
        catalog = load_capability_catalog()
        policy = policy_for_score_version("local_coding_score_v2", catalog=catalog)
        observations = [
            {
                "score_version": "local_coding_score_v2",
                "surface_id": "local_coding_capability",
                "score": 0.55 + index / 100.0,
                "model_family": "Qwen3.6",
                "parameter_band": "20b_to_under_40b",
                "model_identities": ["qwen3627b"],
                "quantization_scheme": "q3_k_m",
                "evidence_group_id": "challenge-source-%d" % index,
                "evidence_group_verified": True,
                "components": [
                    {"benchmark_id": "evalplus_humaneval", "score": 0.6},
                    {"benchmark_id": "evalplus_mbpp", "score": 0.5},
                ],
            }
            for index in range(2)
        ]

        partial = audit_capability_observations(
            observations,
            "local_coding_score_v2",
            policy=policy,
            catalog=catalog,
        )

        self.assertEqual(partial["metrics"]["headroom_challenge_candidate_observation_count"], 2)
        self.assertEqual(partial["metrics"]["headroom_challenge_incomplete_observation_count"], 2)
        self.assertEqual(partial["metrics"]["headroom_challenge_observation_count"], 0)
        self.assertIn(
            "insufficient_headroom_challenge_observation_count",
            partial["blockers"],
        )
        for observation in observations:
            observation["components"].append({
                "benchmark_id": "coding_static_repair_v1",
                "score": 0.4,
            })
        complete = audit_capability_observations(
            observations,
            "local_coding_score_v2",
            policy=policy,
            catalog=catalog,
        )

        self.assertEqual(complete["metrics"]["headroom_challenge_observation_count"], 2)
        self.assertEqual(complete["metrics"]["headroom_challenge_incomplete_observation_count"], 0)
        self.assertEqual(
            complete["metrics"]["headroom_challenge_independently_replicated_setup_count"],
            1,
        )
        self.assertFalse(any(
            blocker.startswith("insufficient_headroom_challenge_")
            for blocker in complete["blockers"]
        ))

    def test_headroom_challenge_does_not_borrow_another_task_lane(self):
        catalog = load_capability_catalog()
        for priority in catalog["coverage_expansion_priorities"]:
            if (
                priority.get("headroom_challenge_eligible") is True
                and priority.get("use_case") == "agentic_coding"
            ):
                priority["headroom_challenge_eligible"] = False
        policy = policy_for_score_version("local_coding_score_v2", catalog=catalog)
        observation = {
            "score_version": "local_coding_score_v2",
            "surface_id": "local_coding_capability",
            "score": 0.55,
            "model_family": "Qwen3.6",
            "parameter_band": "20b_to_under_40b",
            "model_identities": ["qwen3627b"],
            "quantization_scheme": "q3_k_m",
            "evidence_group_id": "coding-source",
            "evidence_group_verified": True,
            "components": [
                {"benchmark_id": "coding_static_repair_v1", "score": 0.4},
                {"benchmark_id": "evalplus_humaneval", "score": 0.6},
                {"benchmark_id": "evalplus_mbpp", "score": 0.5},
            ],
        }

        report = audit_capability_observations(
            [observation],
            "local_coding_score_v2",
            policy=policy,
            catalog=catalog,
        )

        self.assertEqual(
            report["metrics"]["headroom_challenge_candidate_observation_count"],
            0,
        )

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
                "evidence_group_id": "group-%d" % (index // 10),
                "evidence_group_verified": True,
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

    def test_evidence_group_requires_trusted_operator_provenance(self):
        document = {
            "result_id": "result-1",
            "evidence_group_id": "runner-one",
            "capability_score_version": "local_assistant_score_v4",
            "capability_score": 0.5,
            "capability_score_ready": True,
        }

        rejected = extract_calibration_observations([document])[0]
        document["evidence_group_provenance"] = "trusted_corpus_operator_v1"
        accepted = extract_calibration_observations([document])[0]

        self.assertEqual(rejected["evidence_group_id"], "")
        self.assertFalse(rejected["evidence_group_verified"])
        self.assertTrue(rejected["evidence_group_claim_rejected"])
        self.assertEqual(accepted["evidence_group_id"], "runner-one")
        self.assertTrue(accepted["evidence_group_verified"])
        self.assertFalse(accepted["evidence_group_claim_rejected"])

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
        policy.pop("minimum_headroom_challenge_observations")
        policy.pop("minimum_headroom_challenge_model_families")
        policy.pop("minimum_headroom_challenge_independently_replicated_setups")
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
                "evidence_group_id": "group-%d" % (index // 10),
                "evidence_group_verified": True,
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

    def test_headline_component_requires_its_own_family_and_size_breadth(self):
        catalog = load_capability_catalog()
        policy = policy_for_score_version("local_reasoning_score_v2", catalog=catalog)
        policy.update({
            "minimum_model_families": 1,
            "minimum_parameter_bands": 1,
            "minimum_unique_setups": 1,
            "minimum_replicated_setups": 0,
            "minimum_independently_replicated_setups": 0,
            "minimum_current_generation_fraction": 0.0,
            "maximum_largest_family_fraction": 1.0,
            "maximum_single_setup_fraction": 1.0,
        })
        observations = []
        for index in range(20):
            component_rows = []
            if index < 8:
                component_rows = [
                    {"benchmark_id": "mmlu_pro_reference_v1", "score": 0.2 + index / 100.0},
                    {"benchmark_id": "reasoning_exact_answer_v1", "score": 0.3 + index / 100.0},
                ]
            observations.append({
                "score_version": "local_reasoning_score_v2",
                "surface_id": "local_reasoning_capability",
                "score": 0.2 + index / 100.0,
                "model_family": "single-component-family" if index < 8 else "other-%d" % (index % 4),
                "parameter_band": "under_3b" if index < 8 else ["3b_to_under_8b", "8b_to_under_20b"][index % 2],
                "model_identities": ["model-%d" % index],
                "quantization_scheme": "q4_k_m",
                "components": component_rows,
            })

        report = audit_capability_observations(
            observations,
            "local_reasoning_score_v2",
            policy=policy,
            catalog=catalog,
        )

        exact = report["metrics"]["headline_components"]["reasoning_exact_answer_v1"]
        self.assertEqual(exact["observation_count"], 8)
        self.assertEqual(exact["model_family_count"], 1)
        self.assertEqual(exact["parameter_band_count"], 1)
        self.assertIn(
            "insufficient_headline_component_model_families:reasoning_exact_answer_v1",
            report["blockers"],
        )
        self.assertIn(
            "insufficient_headline_component_parameter_bands:reasoning_exact_answer_v1",
            report["blockers"],
        )
        self.assertEqual(report["status"], "insufficient_calibration")
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
                "evidence_group_id": "group-%d" % (index // 10),
                "evidence_group_verified": True,
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

    def test_headline_component_requires_independent_setup_repeats_before_ceiling_judgment(self):
        catalog = load_capability_catalog()
        policy = policy_for_score_version("local_reasoning_score_v2", catalog=catalog)
        policy.update({
            "minimum_observations": 8,
            "minimum_model_families": 1,
            "minimum_parameter_bands": 1,
            "minimum_unique_setups": 1,
            "minimum_replicated_setups": 0,
            "minimum_independently_replicated_setups": 0,
            "minimum_current_generation_fraction": 0.0,
            "maximum_largest_family_fraction": 1.0,
            "maximum_single_setup_fraction": 1.0,
        })
        observations = [
            {
                "score_version": "local_reasoning_score_v2",
                "surface_id": "local_reasoning_capability",
                "score": 0.2 + index / 100.0,
                "model_family": "family-%d" % (index % 4),
                "parameter_band": ["under_3b", "8b_to_under_20b"][index % 2],
                "model_identities": ["model-%d" % (index % 4)],
                "quantization_scheme": "q4_k_m",
                "evidence_group_id": "one-source",
                "evidence_group_verified": True,
                "components": [
                    {"benchmark_id": "mmlu_pro_reference_v1", "score": 1.0},
                    {"benchmark_id": "reasoning_exact_answer_v1", "score": 1.0},
                ],
            }
            for index in range(8)
        ]

        same_source = audit_capability_observations(
            observations,
            "local_reasoning_score_v2",
            policy=policy,
            catalog=catalog,
        )

        exact = same_source["metrics"]["headline_components"]["reasoning_exact_answer_v1"]
        self.assertEqual(exact["model_family_count"], 4)
        self.assertEqual(exact["parameter_band_count"], 2)
        self.assertEqual(exact["evidence_group_count"], 1)
        self.assertEqual(exact["independently_replicated_setup_count"], 0)
        self.assertIn(
            "insufficient_headline_component_independently_replicated_setups:reasoning_exact_answer_v1",
            same_source["blockers"],
        )
        self.assertNotIn(
            "headline_component_ceiling_fraction_above_limit:reasoning_exact_answer_v1",
            same_source["blockers"],
        )
        self.assertEqual(same_source["status"], "insufficient_calibration")

        untrusted_claims = [
            dict(
                observation,
                evidence_group_id="claimed-source-%d" % (index // 4),
                evidence_group_verified=False,
            )
            for index, observation in enumerate(observations)
        ]
        untrusted_report = audit_capability_observations(
            untrusted_claims,
            "local_reasoning_score_v2",
            policy=policy,
            catalog=catalog,
        )
        untrusted_exact = untrusted_report["metrics"]["headline_components"][
            "reasoning_exact_answer_v1"
        ]
        self.assertEqual(untrusted_exact["evidence_group_count"], 0)
        self.assertEqual(untrusted_exact["ungrouped_observation_count"], 8)
        self.assertEqual(untrusted_exact["independently_replicated_setup_count"], 0)
        self.assertIn(
            "insufficient_headline_component_independently_replicated_setups:reasoning_exact_answer_v1",
            untrusted_report["blockers"],
        )

        independently_repeated = [
            dict(observation, evidence_group_id="source-%d" % (index // 4))
            for index, observation in enumerate(observations)
        ]
        repeated_report = audit_capability_observations(
            independently_repeated,
            "local_reasoning_score_v2",
            policy=policy,
            catalog=catalog,
        )
        repeated_exact = repeated_report["metrics"]["headline_components"][
            "reasoning_exact_answer_v1"
        ]
        self.assertEqual(repeated_exact["evidence_group_count"], 2)
        self.assertEqual(repeated_exact["independently_replicated_setup_count"], 4)
        self.assertNotIn(
            "insufficient_headline_component_independently_replicated_setups:reasoning_exact_answer_v1",
            repeated_report["blockers"],
        )
        self.assertIn(
            "headline_component_ceiling_fraction_above_limit:reasoning_exact_answer_v1",
            repeated_report["blockers"],
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
                "evidence_group_id": "same-source",
                "evidence_group_verified": True,
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
        self.assertEqual(report["metrics"]["independently_replicated_setup_count"], 0)
        self.assertEqual(report["metrics"]["current_generation_fraction"], 0.0)
        self.assertIn("insufficient_unique_setup_count", report["blockers"])
        self.assertIn("insufficient_replicated_setup_count", report["blockers"])
        self.assertIn("insufficient_independently_replicated_setup_count", report["blockers"])
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

    def test_same_source_repeats_cannot_satisfy_independent_replication_gate(self):
        policy = {
            "minimum_observations": 8,
            "minimum_model_families": 1,
            "minimum_parameter_bands": 1,
            "minimum_distinct_scores": 2,
            "minimum_replicated_setups": 4,
            "minimum_independently_replicated_setups": 4,
            "maximum_suite_ceiling_fraction": 1.0,
            "maximum_largest_family_fraction": 1.0,
        }
        observations = [
            {
                "score_version": "score-v1",
                "score": 0.2 + index / 100.0,
                "model_family": "family",
                "parameter_band": "3b_to_under_8b",
                "model_identities": ["model-%d" % (index % 4)],
                "quantization_scheme": "q4_k_m",
                "evidence_group_id": "one-runner",
                "evidence_group_verified": True,
            }
            for index in range(8)
        ]

        report = audit_capability_observations(observations, "score-v1", policy=policy)

        self.assertEqual(report["metrics"]["replicated_setup_count"], 4)
        self.assertEqual(report["metrics"]["independently_replicated_setup_count"], 0)
        self.assertEqual(report["metrics"]["evidence_group_count"], 1)
        self.assertIn("insufficient_independently_replicated_setup_count", report["blockers"])
        self.assertFalse(report["headline_ready"])

    def test_distinct_trusted_evidence_groups_satisfy_independent_replication_gate(self):
        observations = [
            {
                "score_version": "score-v1",
                "score": 0.2 + index / 100.0,
                "model_family": "family",
                "parameter_band": "3b_to_under_8b",
                "model_identities": ["model-%d" % (index % 4)],
                "quantization_scheme": "q4_k_m",
                "evidence_group_id": "runner-%d" % (index // 4),
                "evidence_group_verified": True,
            }
            for index in range(8)
        ]
        policy = {
            "minimum_observations": 8,
            "minimum_model_families": 1,
            "minimum_parameter_bands": 1,
            "minimum_distinct_scores": 2,
            "minimum_replicated_setups": 4,
            "minimum_independently_replicated_setups": 4,
            "maximum_suite_ceiling_fraction": 1.0,
            "maximum_largest_family_fraction": 1.0,
        }

        report = audit_capability_observations(observations, "score-v1", policy=policy)

        self.assertEqual(report["metrics"]["independently_replicated_setup_count"], 4)
        self.assertEqual(report["metrics"]["evidence_group_count"], 2)
        self.assertTrue(report["headline_ready"])

    def test_bundle_dedup_prefers_result_with_component_and_setup_detail(self):
        documents = [
            {
                "_source": "/tmp/bundle/artifacts/capability/capability_summary.json",
                "artifact_kind": "capability_summary",
                "bundle_id": "bundle-1",
                "surfaces": [
                    {
                        "surface": "local_reasoning_capability",
                        "score_version": "local_reasoning_score_v2",
                        "score_raw_attainment": 0.64,
                        "score_ready": True,
                    }
                ],
            },
            {
                "_source": "/tmp/bundle/results/result.json",
                "result_id": "result-1",
                "model_id": "Qwen/Qwen3.5-9B",
                "model_family": "Qwen3.5",
                "parameter_scale": "9B",
                "quantization_scheme": "q4_k_m",
                "capability_score_version": "local_reasoning_score_v2",
                "capability_score": 0.64,
                "capability_score_ready": True,
                "capability_component_reports": [
                    {
                        "benchmark_id": "reasoning_exact_answer_v1",
                        "component_score": 1.0,
                        "status": "completed",
                    }
                ],
            },
        ]

        observations = extract_calibration_observations(
            documents,
            score_version="local_reasoning_score_v2",
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["observation_id"], "result-1")
        self.assertEqual(observations[0]["quantization_scheme"], "q4_k_m")
        self.assertEqual(
            observations[0]["components"],
            [{"benchmark_id": "reasoning_exact_answer_v1", "score": 1.0}],
        )

    def test_bundle_dedup_is_order_independent(self):
        summary = {
            "_source": "/tmp/bundle/artifacts/capability/capability_summary.json",
            "artifact_kind": "capability_summary",
            "bundle_id": "bundle-1",
            "surfaces": [{
                "surface": "local_assistant_capability",
                "score_version": "local_assistant_score_v4",
                "score_raw_attainment": 0.5,
                "score_ready": True,
            }],
        }
        result = {
            "_source": "/tmp/bundle/results/result.json",
            "result_id": "result-1",
            "capability_score_version": "local_assistant_score_v4",
            "capability_score": 0.5,
            "capability_score_ready": True,
            "capability_component_reports": [{
                "benchmark_id": "ifeval",
                "component_score": 0.5,
                "status": "completed",
            }],
        }

        forward = extract_calibration_observations([summary, result])
        reverse = extract_calibration_observations([result, summary])

        self.assertEqual(forward, reverse)

    def test_bundle_dedup_marks_conflicting_composite_scores_and_excludes_them(self):
        documents = [
            {
                "_source": "/tmp/bundle/artifacts/capability/capability_summary.json",
                "artifact_kind": "capability_summary",
                "bundle_id": "bundle-1",
                "surfaces": [{
                    "surface": "local_assistant_capability",
                    "score_version": "local_assistant_score_v4",
                    "score_raw_attainment": 0.5,
                    "score_ready": True,
                }],
            },
            {
                "_source": "/tmp/bundle/results/result.json",
                "result_id": "result-1",
                "capability_score_version": "local_assistant_score_v4",
                "capability_score": 0.6,
                "capability_score_ready": True,
                "capability_component_reports": [{
                    "benchmark_id": "ifeval",
                    "component_score": 0.5,
                    "status": "completed",
                }],
            },
        ]

        observations = extract_calibration_observations(documents)
        report = audit_capability_observations(observations, "local_assistant_score_v4")

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["integrity_conflicts"], ["composite_score_mismatch"])
        self.assertEqual(report["status"], "evidence_integrity_risk")
        self.assertFalse(report["headline_ready"])
        self.assertEqual(report["metrics"]["integrity_conflict_count"], 1)
        self.assertEqual(report["metrics"]["observation_count"], 0)
        self.assertIn("duplicate_observation_integrity_conflict", report["blockers"])

    def test_bundle_dedup_marks_conflicting_component_scores(self):
        result = {
            "_source": "/tmp/bundle/results/result.json",
            "result_id": "result-1",
            "capability_score_version": "local_assistant_score_v4",
            "capability_score": 0.5,
            "capability_score_ready": True,
            "capability_component_reports": [{
                "benchmark_id": "ifeval",
                "component_score": 0.5,
                "status": "completed",
            }],
        }
        second_view = dict(result)
        second_view["_source"] = "/tmp/bundle/artifacts/normalized_result.json"
        second_view["capability_component_reports"] = [{
            "benchmark_id": "ifeval",
            "component_score": 0.75,
            "status": "completed",
        }]

        observations = extract_calibration_observations([result, second_view])

        self.assertEqual(len(observations), 1)
        self.assertEqual(
            observations[0]["integrity_conflicts"],
            ["component_score_mismatch:ifeval"],
        )

    def test_bundle_dedup_marks_conflicting_trusted_evidence_groups(self):
        first = {
            "_source": "/tmp/bundle/results/result.json",
            "result_id": "result-1",
            "evidence_group_id": "runner-one",
            "evidence_group_provenance": "trusted_corpus_operator_v1",
            "capability_score_version": "local_assistant_score_v4",
            "capability_score": 0.5,
            "capability_score_ready": True,
        }
        second = dict(first)
        second["_source"] = "/tmp/bundle/artifacts/normalized_result.json"
        second["evidence_group_id"] = "runner-two"

        observations = extract_calibration_observations([first, second])

        self.assertEqual(observations[0]["integrity_conflicts"], ["evidence_group_mismatch"])

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
