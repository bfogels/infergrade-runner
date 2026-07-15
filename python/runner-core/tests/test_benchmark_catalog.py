import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, "python/runner-core/src")

import infergrade.paths as runner_paths
from infergrade.benchmark_catalog import (
    benchmark_scope_summary_for_selection,
    benchmark_status_index,
    capability_coverage_guidance_for_selection,
    capability_benchmark_ids_for_request,
    capability_surface_index,
    coverage_expansion_priorities,
    evidence_lane_index,
    fidelity_enabled_for_request,
    load_capability_catalog,
    normalize_request_selection,
    selection_metadata_for_request,
    shortcut_selection,
    surface_score_policy_index,
    validate_benchmark_legitimacy_metadata,
)
from infergrade.models import RunRequest


class BenchmarkCatalogTests(unittest.TestCase):
    def test_capability_catalog_exposes_suites_groups_and_checks(self):
        catalog = load_capability_catalog()
        self.assertGreaterEqual(len(catalog["suites"]), 3)
        self.assertGreaterEqual(len(catalog["benchmark_groups"]), 5)
        self.assertGreaterEqual(len(catalog["checks"]), 6)
        self.assertIn("metadata_ordering", catalog)
        self.assertIn("coverage_expansion_priorities", catalog)
        self.assertTrue(catalog["score_policies"])
        self.assertIn("evidence_lanes", catalog)
        self.assertIn("benchmark_maturity_levels", catalog)
        self.assertIn("benchmark_status_matrix", catalog)
        self.assertEqual([item["lane_id"] for item in catalog["evidence_lanes"]], ["smoke", "decision", "reference", "gold"])
        self.assertIn("capability_surfaces", catalog)
        self.assertIn("surface_score_policies", catalog)
        self.assertEqual(
            set(item["surface_id"] for item in catalog["capability_surfaces"]),
            {
                "local_assistant_capability",
                "local_coding_capability",
                "local_reasoning_capability",
                "quant_fidelity",
                "deployment_fitness",
            },
        )
        self.assertEqual(catalog["metadata_source_defaults"]["duration"], "estimated")
        self.assertEqual(catalog["benchmark_scopes"][0]["scope_id"], "decision")
        surface_ids = set(capability_surface_index(catalog))
        check_ids = {item["check_id"] for item in catalog["checks"]}
        planned_ids = {item["check_id"] for item in catalog["planned_benchmark_candidates"]}
        self.assertIn("multiturn_chat_memory_v1", check_ids)
        self.assertIn("assistant_compositional_instruction_v2", check_ids)
        self.assertIn("coding_static_repair_v1", check_ids)
        self.assertIn("reasoning_exact_answer_v1", check_ids)
        self.assertIn("mmlu_pro_reference_v1", check_ids)
        self.assertNotIn("multiturn_chat_memory_v1", planned_ids)
        self.assertNotIn("coding_static_repair_v1", planned_ids)
        self.assertNotIn("reasoning_exact_answer_v1", planned_ids)
        self.assertNotIn("mmlu_pro_reference_v1", planned_ids)
        for check in catalog["checks"]:
            self.assertIn(check["suite_scope"], {"decision", "reference"})
            self.assertIn(check["evidence_lane_id"], {"smoke", "decision", "reference", "gold"})
            self.assertIn(check["surface_id"], surface_ids)
            self.assertTrue(check["expected_duration_band"])
            self.assertTrue(check["execution_pattern"])
            self.assertTrue(check["score_dimension"])
            self.assertTrue(check["primary_score_metric"])
            self.assertIn("higher_is_better", check)
            self.assertIn("score_floor", check)
            self.assertIn("primary_score_weight", check)
            self.assertTrue(check["score_policy_id"])
        self.assertTrue(catalog["planned_benchmark_candidates"])
        score_policies = surface_score_policy_index(catalog)
        self.assertEqual(score_policies["local_assistant_capability"]["score_version"], "local_assistant_score_v4")
        self.assertEqual(score_policies["local_assistant_capability"]["protocol_version"], "3.1")
        self.assertEqual(score_policies["local_assistant_capability"]["protocol_label"], "Capability protocol v3.1")
        self.assertEqual(score_policies["local_assistant_capability"]["scale_interpretation"], "benchmark_attainment_index")
        calibration_policy = score_policies["local_assistant_capability"]["calibration_policy"]
        self.assertEqual(calibration_policy["policy_id"], "capability_headroom_gate_v2")
        self.assertEqual(calibration_policy["minimum_unique_setups"], 8)
        self.assertEqual(calibration_policy["minimum_replicated_setups"], 4)
        self.assertEqual(calibration_policy["minimum_current_generation_fraction"], 0.75)
        self.assertEqual(calibration_policy["maximum_single_setup_fraction"], 0.25)
        self.assertEqual(score_policies["local_coding_capability"]["minimum_coverage_fraction"], 0.5)
        self.assertEqual(score_policies["local_coding_capability"]["minimum_scored_components"], 2)
        self.assertEqual(score_policies["local_coding_capability"]["minimum_score_dimensions"], 2)
        self.assertEqual(score_policies["local_coding_capability"]["maximum_component_weight_fraction"], 0.8)

    def test_coverage_expansion_priorities_are_ordered_and_answer_loop_scoped(self):
        priorities = coverage_expansion_priorities()

        self.assertGreaterEqual(len(priorities), 4)
        self.assertEqual([item["rank"] for item in priorities], sorted(item["rank"] for item in priorities))
        first = priorities[0]
        self.assertEqual(first["priority_id"], "apple_silicon_qwen35_9b_assistant_repeat")
        self.assertEqual(first["model_id"], "Qwen/Qwen3.5-9B")
        self.assertEqual(first["use_case"], "general_assistant")
        self.assertEqual(first["model_freshness"], "current_generation")
        self.assertEqual(first["campaign_role"], "current_anchor")
        self.assertEqual(first["target_observations"], 2)
        self.assertIn("perplexity_reference_v1", first["benchmark_check_ids"])
        qwen3 = next(item for item in priorities if item["priority_id"] == "apple_silicon_qwen3_8b_assistant_repeat")
        self.assertEqual(qwen3["model_family"], "Qwen3")
        self.assertEqual(qwen3["model_id"], "Qwen/Qwen3-8B")
        self.assertEqual(qwen3["target_quants"], ["q4_k_m"])
        self.assertEqual(qwen3["use_case"], "general_assistant")
        self.assertEqual(qwen3["generation_preset_id"], "deterministic_direct_answer_v1")
        self.assertEqual(qwen3["status"], "needs_exact_repeat")
        self.assertIn("multiturn_chat_memory_v1", qwen3["benchmark_check_ids"])
        qwen35 = first
        self.assertEqual(qwen35["model_family"], "Qwen3.5")
        self.assertEqual(qwen35["target_quants"], ["q4_k_m"])
        self.assertEqual(qwen35["generation_preset_id"], "deterministic_direct_answer_v1")
        self.assertEqual(qwen35["status"], "needs_exact_repeat")
        qwen_sub1b = next(
            item for item in priorities
            if item["priority_id"] == "apple_silicon_qwen3_sub1b_calibration_band"
        )
        self.assertEqual(qwen_sub1b["model_id"], "Qwen/Qwen3-0.6B")
        self.assertEqual(qwen_sub1b["parameter_scale"], "0.6B")
        self.assertEqual(qwen_sub1b["target_quants"], ["q8_0"])
        self.assertEqual(qwen_sub1b["generation_preset_id"], "deterministic_direct_answer_v1")
        ministral = next(
            item for item in priorities
            if item["priority_id"] == "apple_silicon_ministral3_3b_assistant_repeat"
        )
        self.assertEqual(ministral["model_family"], "Ministral-3")
        self.assertEqual(ministral["parameter_scale"], "3B")
        gemma4 = next(
            item for item in priorities
            if item["priority_id"] == "apple_silicon_gemma4_e4b_assistant_repeat"
        )
        self.assertEqual(gemma4["target_quants"], ["q4_0"])
        self.assertEqual(gemma4["parameter_scale"], "E4B")
        qwen36 = next(
            item for item in priorities
            if item["priority_id"] == "apple_silicon_qwen36_27b_assistant_canary"
        )
        self.assertEqual(qwen36["model_freshness"], "current_generation")
        self.assertEqual(qwen36["campaign_availability"], "blocked_pending_canary")
        self.assertIn("24gb", qwen36["blocked_reason"])
        coding_anchor = next(
            item for item in priorities
            if item["priority_id"] == "apple_silicon_qwen35_9b_coding_anchor"
        )
        reasoning_anchor = next(
            item for item in priorities
            if item["priority_id"] == "apple_silicon_qwen35_9b_reasoning_anchor"
        )
        self.assertEqual(coding_anchor["model_id"], "Qwen/Qwen3.5-9B")
        self.assertEqual(coding_anchor["use_case"], "agentic_coding")
        self.assertEqual(
            coding_anchor["benchmark_check_ids"],
            ["interactive_chat_v1", "evalplus_humaneval", "evalplus_mbpp"],
        )
        self.assertEqual(reasoning_anchor["use_case"], "reasoning")
        self.assertEqual(
            reasoning_anchor["benchmark_check_ids"],
            ["reasoning_exact_answer_v1", "mmlu_pro_reference_v1"],
        )
        self.assertTrue(coding_anchor["calibration_campaign_eligible"])
        self.assertTrue(reasoning_anchor["calibration_campaign_eligible"])
        historical = next(
            item for item in priorities
            if item["priority_id"] == "apple_silicon_qwen25_historical_quant_control"
        )
        self.assertEqual(historical["queue_policy"], "demand_only")
        self.assertFalse(historical["calibration_campaign_eligible"])
        self.assertEqual(historical["model_freshness"], "historical_control")
        for priority in priorities:
            self.assertIn(priority["queue_policy"], {"campaign", "demand_only", "platform_gate"})
            self.assertIn(
                priority["campaign_availability"],
                {"reviewed_runnable", "blocked_pending_canary"},
            )
        cuda = next(item for item in priorities if item["priority_id"] == "windows_nvidia_cuda_beta_gate")
        self.assertEqual(cuda["status"], "hardware_blocked")
        self.assertIn("full loop", cuda["why"])

    def test_packaged_resource_root_can_be_resolved_from_runner_core_src(self):
        with tempfile.TemporaryDirectory() as tempdir:
            resources = Path(tempdir) / "InferGrade Runner.app" / "Contents" / "Resources"
            (resources / "runner-core" / "src" / "infergrade").mkdir(parents=True)
            (resources / "schemas").mkdir()
            previous_file = runner_paths.__file__
            try:
                runner_paths.__file__ = str(
                    resources / "runner-core" / "src" / "infergrade" / "paths.py"
                )
                self.assertEqual(runner_paths.runner_root(), resources.resolve())
            finally:
                runner_paths.__file__ = previous_file

    def test_catalog_legitimacy_metadata_is_complete_and_conservative(self):
        catalog = load_capability_catalog()
        self.assertEqual(validate_benchmark_legitimacy_metadata(catalog), [])
        statuses = benchmark_status_index(catalog)
        required_ids = {
            "multiturn_chat_memory_v1",
            "coding_static_repair_v1",
            "reasoning_exact_answer_v1",
            "mmlu_pro_reference_v1",
            "evalplus_humaneval",
            "evalplus_mbpp",
            "perplexity_reference_v1",
            "gpqa_reference_v1",
            "livecodebench_reference_v1",
            "swebench_verified_gold_v1",
            "repository_edit_smoke_v1",
        }
        self.assertTrue(required_ids.issubset(set(statuses)))
        self.assertEqual(statuses["multiturn_chat_memory_v1"]["maturity"], "thin_local_sample")
        self.assertEqual(statuses["coding_static_repair_v1"]["maturity"], "thin_local_sample")
        self.assertEqual(statuses["reasoning_exact_answer_v1"]["maturity"], "thin_local_sample")
        self.assertEqual(statuses["mmlu_pro_reference_v1"]["maturity"], "reference_runnable")
        self.assertEqual(statuses["perplexity_reference_v1"]["maturity"], "reference_runnable")
        self.assertEqual(statuses["perplexity_reference_v1"]["surface_id"], "quant_fidelity")
        self.assertIn("Same-family quant-fidelity", statuses["perplexity_reference_v1"]["claim_boundary"])
        self.assertEqual(statuses["swebench_verified_gold_v1"]["maturity"], "gold_candidate")
        self.assertEqual(statuses["swebench_verified_gold_v1"]["runnable_status"], "not_runnable")
        self.assertIn("not runnable", statuses["swebench_verified_gold_v1"]["claim_boundary"])
        for check_id in ("multiturn_chat_memory_v1", "coding_static_repair_v1", "reasoning_exact_answer_v1"):
            self.assertEqual(statuses[check_id]["evidence_lane_id"], "decision")
            self.assertNotIn("reference", statuses[check_id]["maturity"])
            self.assertNotIn("gold", statuses[check_id]["maturity"])
            self.assertTrue(statuses[check_id]["promotion_blockers"])

    def test_catalog_legitimacy_validation_rejects_weak_or_mismatched_status(self):
        catalog = load_capability_catalog()
        mutated = deepcopy(catalog)
        statuses = {item["check_id"]: item for item in mutated["benchmark_status_matrix"]}
        statuses["multiturn_chat_memory_v1"]["claim_boundary"] = ""
        statuses["multiturn_chat_memory_v1"]["runnable_status"] = ""
        statuses["multiturn_chat_memory_v1"]["scoring_policy_id"] = "typo_policy_v1"
        next(
            item for item in mutated["checks"] if item["check_id"] == "multiturn_chat_memory_v1"
        )["score_policy_id"] = "other_typo_policy_v1"
        statuses["gpqa_reference_v1"]["scoring_policy_id"] = "typo_policy_v1"
        failures = validate_benchmark_legitimacy_metadata(mutated)
        self.assertTrue(any("status field claim_boundary must be non-empty" in item for item in failures))
        self.assertTrue(any("status field runnable_status must be non-empty" in item for item in failures))
        self.assertTrue(any("multiturn_chat_memory_v1" in item and "does not match check" in item for item in failures))
        self.assertTrue(any("multiturn_chat_memory_v1" in item and "is not declared" in item for item in failures))
        self.assertTrue(any("gpqa_reference_v1" in item and "does not match planned" in item for item in failures))

    def test_catalog_legitimacy_validation_rejects_unknown_coverage_generation_preset(self):
        mutated = deepcopy(load_capability_catalog())
        priority = next(
            item
            for item in mutated["coverage_expansion_priorities"]
            if item["priority_id"] == "apple_silicon_qwen3_8b_assistant_repeat"
        )
        priority["generation_preset_id"] = "typo_direct_answer_v1"

        failures = validate_benchmark_legitimacy_metadata(mutated)

        self.assertIn(
            "apple_silicon_qwen3_8b_assistant_repeat: unsupported coverage generation_preset_id "
            "'typo_direct_answer_v1'",
            failures,
        )

    def test_catalog_protocol_name_requires_a_versioned_label_pair(self):
        mutated = deepcopy(load_capability_catalog())
        policy = next(
            item
            for item in mutated["surface_score_policies"]
            if item["surface_id"] == "local_assistant_capability"
        )
        policy.pop("protocol_label")
        policy["protocol_version"] = "3"

        failures = validate_benchmark_legitimacy_metadata(mutated)

        self.assertIn(
            "local_assistant_capability: protocol_version and protocol_label must be declared together",
            failures,
        )
        self.assertIn(
            "local_assistant_capability: protocol_version must use major.minor notation",
            failures,
        )

    def test_catalog_legitimacy_validation_accepts_explicit_default_generation_preset(self):
        mutated = deepcopy(load_capability_catalog())
        priority = next(
            item
            for item in mutated["coverage_expansion_priorities"]
            if item["priority_id"] == "apple_silicon_qwen3_8b_assistant_repeat"
        )
        priority["generation_preset_id"] = "deterministic_v1"

        self.assertEqual(validate_benchmark_legitimacy_metadata(mutated), [])

    def test_evidence_lane_index_exposes_claim_boundaries(self):
        lanes = evidence_lane_index()
        self.assertEqual(lanes["smoke"]["claim_strength"], "execution_smoke")
        self.assertEqual(lanes["decision"]["claim_strength"], "first_pass_local_decision")
        self.assertIn("leaderboard-style", lanes["decision"]["claim_boundary"])
        self.assertEqual(lanes["reference"]["local_feasibility"], "intentional_local")
        self.assertEqual(lanes["gold"]["local_feasibility"], "curated_or_cloud_first")

    def test_normalize_request_selection_derives_breadth_from_legacy_lane(self):
        request = RunRequest(model="Qwen/Qwen2.5-7B-Instruct", backend="llama.cpp", tier="standard", use_case="general_assistant")
        normalize_request_selection(request)
        self.assertIn("chat_instruction_following", request.capability_suite_ids)
        self.assertIn("instruction_following", request.benchmark_group_ids)
        self.assertIn("chat_memory", request.benchmark_group_ids)
        self.assertIn("ifeval", request.benchmark_check_ids)
        self.assertIn("multiturn_chat_memory_v1", request.benchmark_check_ids)
        self.assertIn("interactive_chat_v1", request.deployment_profiles)

    def test_native_multiturn_check_can_be_selected_explicitly(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            benchmark_group_ids=["chat_memory"],
        )
        normalize_request_selection(request)
        self.assertEqual(request.benchmark_group_ids, ["chat_memory"])
        self.assertEqual(request.benchmark_check_ids, ["multiturn_chat_memory_v1"])
        self.assertEqual(capability_benchmark_ids_for_request(request), ["multiturn_chat_memory_v1"])
        self.assertEqual(request.capability, "auto")

    def test_native_coding_static_check_can_be_selected_explicitly(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            benchmark_group_ids=["coding_static_repair"],
        )
        normalize_request_selection(request)
        self.assertEqual(request.benchmark_group_ids, ["coding_static_repair"])
        self.assertEqual(request.benchmark_check_ids, ["coding_static_repair_v1"])
        self.assertEqual(capability_benchmark_ids_for_request(request), ["coding_static_repair_v1"])
        self.assertEqual(request.use_case, "agentic_coding")
        self.assertEqual(request.capability, "auto")

    def test_native_reasoning_exact_answer_check_can_be_selected_explicitly(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            benchmark_group_ids=["reasoning_exact_answer"],
        )
        normalize_request_selection(request)
        self.assertEqual(request.benchmark_group_ids, ["reasoning_exact_answer"])
        self.assertEqual(request.benchmark_check_ids, ["reasoning_exact_answer_v1"])
        self.assertEqual(capability_benchmark_ids_for_request(request), ["reasoning_exact_answer_v1"])
        self.assertEqual(request.capability, "auto")

    def test_reasoning_suite_resolves_to_reasoning_use_case(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            capability_suite_ids=["reasoning_problem_solving"],
        )
        normalize_request_selection(request)
        self.assertEqual(request.use_case, "reasoning")
        self.assertIn("reasoning_exact_answer_v1", request.benchmark_check_ids)

    def test_assistant_suite_defaults_do_not_mix_reasoning_surface(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            capability_suite_ids=["chat_instruction_following"],
        )
        normalize_request_selection(request)
        self.assertIn("multiturn_chat_memory_v1", request.benchmark_check_ids)
        self.assertNotIn("reasoning_exact_answer_v1", request.benchmark_check_ids)

    def test_shortcut_selection_resolves_catalog_shortcut(self):
        selection = shortcut_selection("quick_default")
        self.assertEqual(selection["suite_ids"], ["chat_instruction_following"])
        self.assertEqual(selection["group_ids"], ["instruction_following", "chat_memory", "assistant_compositional", "deployment_chat"])
        self.assertEqual(
            selection["check_ids"],
            ["ifeval", "multiturn_chat_memory_v1", "assistant_compositional_instruction_v2", "interactive_chat_v1"],
        )

    def test_assistant_reference_shortcut_adds_mmlu_pro_intentionally(self):
        selection = shortcut_selection("assistant_reference")
        self.assertIn("broad_reasoning_knowledge", selection["group_ids"])
        self.assertIn("mmlu_pro_reference_v1", selection["check_ids"])
        self.assertNotIn("mmlu_pro_reference_v1", shortcut_selection("quick_default")["check_ids"])

    def test_normalize_request_selection_uses_shortcut_before_legacy_lane(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            use_case="general_assistant",
            benchmark_shortcut_id="broad_compare",
        )
        normalize_request_selection(request)
        self.assertEqual(request.capability_suite_ids, ["chat_instruction_following", "quant_fidelity"])
        self.assertEqual(
            request.benchmark_check_ids,
            [
                "ifeval",
                "multiturn_chat_memory_v1",
                "interactive_chat_v1",
                "batch_generation_v1",
                "perplexity_reference_v1",
            ],
        )
        self.assertEqual(request.deployment_profiles, ["interactive_chat_v1", "batch_generation_v1"])
        self.assertEqual(request.tier, "gold")

    def test_unknown_shortcut_falls_back_to_legacy_lane(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            use_case="general_assistant",
            benchmark_shortcut_id="missing_shortcut",
        )
        normalize_request_selection(request)
        self.assertEqual(request.benchmark_check_ids, ["ifeval", "interactive_chat_v1"])

    def test_explicit_selection_takes_precedence_over_shortcut(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_shortcut_id="broad_compare",
            capability_suite_ids=["coding_code_editing"],
            benchmark_group_ids=["coding_core"],
            benchmark_check_ids=["evalplus_humaneval"],
        )
        normalize_request_selection(request)
        self.assertEqual(request.capability_suite_ids, ["coding_code_editing"])
        self.assertEqual(request.benchmark_group_ids, ["coding_core"])
        self.assertEqual(request.benchmark_check_ids, ["evalplus_humaneval"])

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
        self.assertEqual(decision["evidence_lane_id"], "decision")
        self.assertEqual(decision["evidence_lane"]["display_name"], "Decision evidence")
        self.assertEqual(decision["claim_strength"], "first_pass_local_decision")
        self.assertIn("recommended short local path", decision["selection_guidance"])
        self.assertEqual(decision["effort_level"], "balanced")
        self.assertFalse(decision["reference_checks_included"])
        self.assertEqual(decision["metadata_sources"]["duration"], "estimated")
        self.assertEqual(decision["metadata_sources"]["failure_rate"], "unknown")
        self.assertEqual(decision["metadata_confidence"], "unknown")

        reference = benchmark_scope_summary_for_selection(["interactive_chat_v1", "perplexity_reference_v1"])
        self.assertEqual(reference["scope"], "reference")
        self.assertEqual(reference["evidence_lane_id"], "reference")
        self.assertEqual(reference["claim_strength"], "stronger_comparison")
        self.assertEqual(reference["scope_label"], "Reference suite")
        self.assertIn("deeper evidence", reference["selection_guidance"])
        self.assertTrue(reference["reference_checks_included"])
        self.assertIn("throughput_oriented_offline_suite", reference["execution_patterns"])

    def test_capability_coverage_guidance_marks_unselected_evidence_as_gap(self):
        guidance = capability_coverage_guidance_for_selection(["interactive_chat_v1"])
        self.assertEqual([item["lane_id"] for item in guidance["evidence_lanes"]], ["smoke", "decision", "reference", "gold"])
        self.assertEqual(guidance["selected_evidence_lane_ids"], ["decision"])
        missing = {item["evidence_kind"]: item for item in guidance["missing_core_evidence"]}
        self.assertEqual(missing["capability"]["state"], "not_selected")
        self.assertIn("not a failed benchmark", missing["capability"]["message"])
        self.assertIn("perplexity_reference_v1", guidance["available_reference_check_ids"])
        self.assertIn("mmlu_pro_reference_v1", guidance["available_reference_check_ids"])
        self.assertTrue(guidance["planned_benchmark_candidates"])
        planned = {item["check_id"]: item for item in guidance["planned_benchmark_candidates"]}
        self.assertNotIn("mmlu_pro_reference_v1", planned)
        self.assertEqual(planned["gpqa_reference_v1"]["status"], "planned_access_gated")
        self.assertEqual(planned["gpqa_reference_v1"]["benchmark_maturity"], "planned")
        self.assertEqual(planned["gpqa_reference_v1"]["runnable_status"], "not_runnable_access_gated")
        self.assertEqual(planned["gpqa_reference_v1"]["harness_status"], "not_implemented")
        self.assertEqual(planned["gpqa_reference_v1"]["access_status"], "gated_contact_share_required")
        self.assertIn("Do not commit", planned["gpqa_reference_v1"]["dataset_handling_policy"])
        self.assertEqual(planned["swebench_verified_gold_v1"]["benchmark_tier"], "gold")
        self.assertEqual(planned["swebench_verified_gold_v1"]["evidence_lane_id"], "gold")
        self.assertEqual(planned["swebench_verified_gold_v1"]["claim_strength"], "curated_reference")
        self.assertEqual(planned["swebench_verified_gold_v1"]["benchmark_maturity"], "gold_candidate")
        self.assertEqual(planned["swebench_verified_gold_v1"]["runnable_status"], "not_runnable")
        self.assertIn("Future gold evidence candidate", planned["swebench_verified_gold_v1"]["benchmark_claim_boundary"])
        self.assertTrue(planned["swebench_verified_gold_v1"]["why_not_default"])
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
        self.assertEqual(interactive["surface_id"], "deployment_fitness")
        self.assertEqual(interactive["evidence_lane_id"], "decision")
        self.assertEqual(interactive["claim_strength"], "first_pass_local_decision")
        self.assertEqual(interactive["benchmark_maturity"], "strong_local_candidate")
        self.assertEqual(interactive["runnable_status"], "runnable_default_local")
        self.assertIn("Deployment fitness evidence only", interactive["benchmark_claim_boundary"])
        self.assertFalse(interactive["higher_is_better"])
        self.assertEqual(interactive["primary_score_weight"], 0.0)
        self.assertIn("time_to_first_token_ms", interactive["score_breakdown_fields"])
        policy_ids = [item["score_policy_id"] for item in metadata["score_policies"]]
        self.assertEqual(policy_ids, ["instruction_following_primary_accuracy_v1", "deployment_profile_metrics_v1"])

    def test_selection_metadata_includes_multiturn_score_policy(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
        )
        metadata = selection_metadata_for_request(request)
        self.assertEqual(metadata["benchmark_checks"][0]["score_dimension"], "multiturn_instruction_retention")
        self.assertEqual(metadata["benchmark_checks"][0]["benchmark_maturity"], "thin_local_sample")
        self.assertIn("Saturated diagnostic assistant microcheck", metadata["benchmark_checks"][0]["benchmark_claim_boundary"])
        self.assertEqual(metadata["benchmark_checks"][0]["score_role"], "diagnostic_only")
        self.assertEqual(metadata["benchmark_checks"][0]["discrimination_status"], "empirically_saturated")
        self.assertEqual(metadata["benchmark_checks"][0]["saturation_evidence"]["suite_ceiling_count"], 35)
        self.assertEqual(metadata["benchmark_checks"][0]["primary_score_metric"], "constraint_retention_accuracy")
        self.assertIn("case_accuracy", metadata["benchmark_checks"][0]["score_breakdown_fields"])
        self.assertEqual(metadata["score_policies"][0]["score_policy_id"], "multiturn_constraint_retention_v1")

    def test_selection_metadata_includes_coding_static_score_policy(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            benchmark_check_ids=["coding_static_repair_v1"],
        )
        metadata = selection_metadata_for_request(request)
        self.assertEqual(metadata["benchmark_scope"]["scope"], "decision")
        self.assertEqual(metadata["benchmark_checks"][0]["surface_id"], "local_coding_capability")
        self.assertEqual(metadata["benchmark_checks"][0]["evidence_lane_id"], "decision")
        self.assertEqual(metadata["benchmark_checks"][0]["score_dimension"], "static_code_repair")
        self.assertEqual(metadata["benchmark_checks"][0]["primary_score_metric"], "static_constraint_accuracy")
        self.assertIn("malformed_output_count", metadata["benchmark_checks"][0]["score_breakdown_fields"])
        self.assertEqual(metadata["score_policies"][0]["score_policy_id"], "coding_static_constraints_v1")

    def test_selection_metadata_includes_reasoning_exact_answer_score_policy(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            benchmark_check_ids=["reasoning_exact_answer_v1"],
        )
        metadata = selection_metadata_for_request(request)
        self.assertEqual(metadata["benchmark_scope"]["scope"], "decision")
        self.assertEqual(metadata["benchmark_checks"][0]["surface_id"], "local_reasoning_capability")
        self.assertEqual(metadata["benchmark_checks"][0]["evidence_lane_id"], "decision")
        self.assertEqual(metadata["benchmark_checks"][0]["score_dimension"], "exact_reasoning")
        self.assertEqual(metadata["benchmark_checks"][0]["primary_score_metric"], "exact_answer_accuracy")
        self.assertIn("correct_count", metadata["benchmark_checks"][0]["score_breakdown_fields"])
        self.assertEqual(metadata["score_policies"][0]["score_policy_id"], "reasoning_exact_answer_v1")

    def test_selection_metadata_includes_mmlu_pro_reference_score_policy(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="gold",
            benchmark_check_ids=["mmlu_pro_reference_v1"],
        )
        metadata = selection_metadata_for_request(request)
        self.assertEqual(metadata["benchmark_scope"]["scope"], "reference")
        self.assertEqual(metadata["benchmark_scope"]["evidence_lane_id"], "reference")
        self.assertEqual(metadata["benchmark_checks"][0]["evidence_lane_id"], "reference")
        self.assertEqual(metadata["benchmark_checks"][0]["score_dimension"], "broad_reasoning_knowledge")
        self.assertEqual(metadata["benchmark_checks"][0]["primary_score_metric"], "accuracy")
        self.assertEqual(
            metadata["score_policies"][0]["score_policy_id"],
            "exact_multiple_choice_letter_accuracy_v2",
        )

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
