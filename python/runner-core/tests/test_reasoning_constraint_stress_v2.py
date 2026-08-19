import hashlib
import json
import sys
import unittest
from copy import deepcopy

sys.path.insert(0, "python/runner-core/src")

from infergrade.reasoning_constraint_stress import (
    FIXTURE_REVISION as V1_FIXTURE_REVISION,
    reasoning_constraint_stress_cases as v1_cases,
)
from infergrade.reasoning_constraint_stress_v2 import (
    ANSWER_VECTOR,
    EXPECTED_ANSWER_VECTOR,
    FINAL_ANSWER_MARKER,
    FINAL_ANSWER_PARSER_ID,
    FIXTURE_SHA256,
    FIXTURE_REVISION,
    FULL_FIXTURE_SHA256,
    MAX_INTEGER_DIGITS,
    SCORING_POLICY,
    SELECTION_DIGEST_ALGORITHM,
    SELECTION_DIGEST_SHA256,
    parse_final_answer,
    reasoning_constraint_stress_v2_cases,
)
from infergrade.benchmark_catalog import (
    FOUNDATION_CANARY_BENCHMARKS,
    FOUNDATION_CANARY_DESCRIPTION,
    FOUNDATION_CANARY_SELECTION_GUIDANCE,
    benchmark_evidence_exclusion_reason,
    benchmark_scope_summary_for_selection,
    capability_benchmark_ids_for_request,
    capability_coverage_guidance_for_selection,
    deployment_profile_ids_for_request,
    fidelity_enabled_for_request,
    load_capability_catalog,
    normalize_request_selection,
    selection_metadata_for_request,
    validate_benchmark_legitimacy_metadata,
)
from infergrade.capabilities import capability_images_for_request
from infergrade.models import RunRequest
from infergrade.selection_identity import selection_digest


class ReasoningConstraintStressV2FixtureTests(unittest.TestCase):
    def test_fixture_is_fresh_six_case_snapshot_with_locked_selection_digest(self):
        cases = reasoning_constraint_stress_v2_cases()
        self.assertEqual(FIXTURE_REVISION, "2026-08-reasoning-constraint-stress-v2")
        self.assertEqual(SCORING_POLICY, "reasoning_constraint_stress_v2_exact_signed_integer_v1")
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({case["case_id"] for case in cases}), 6)
        self.assertEqual(len({case["task_id"] for case in cases}), 6)
        self.assertTrue(all(case["task_id"].startswith("reasoning_constraint_stress_v2/") for case in cases))
        self.assertTrue(set(case["task_id"] for case in cases).isdisjoint(set(item["task_id"] for item in v1_cases())))
        self.assertTrue(set(case["case_id"] for case in cases).isdisjoint(set(item["case_id"] for item in v1_cases())))
        self.assertEqual(
            SELECTION_DIGEST_SHA256,
            selection_digest(
                [case["task_id"] for case in cases],
                SELECTION_DIGEST_ALGORITHM,
            ),
        )
        self.assertEqual(SELECTION_DIGEST_SHA256, "7d384656457dfeab9c61e25af798c4ed5db19321a04ae088b9ba2bdc4a5b02e0")
        self.assertTrue(all(case["expected_answers"] for case in cases))
        self.assertEqual(
            tuple(case["expected_answers"][0] for case in cases),
            EXPECTED_ANSWER_VECTOR,
        )
        self.assertEqual(ANSWER_VECTOR, ("-6", "22", "4", "126", "15", "4133"))
        self.assertEqual(FIXTURE_SHA256, "899960f108683f21f531772e791441c9912c25569f8c080c0ad61095af022762")
        self.assertEqual(FULL_FIXTURE_SHA256, FIXTURE_SHA256)
        self.assertEqual(
            hashlib.sha256(
                json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            FIXTURE_SHA256,
        )

    def test_v1_fixture_revision_and_digest_remain_immutable(self):
        cases = v1_cases()
        self.assertEqual(V1_FIXTURE_REVISION, "2026-08-reasoning-constraint-stress-v1")
        self.assertEqual(
            hashlib.sha256(
                json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "57de9422faaf62b22c2e21427f63553b0267928cd4e5b0a69165744be90a1cec",
        )


class ReasoningConstraintStressV2ParserTests(unittest.TestCase):
    def test_reasoning_before_one_terminal_signed_integer_is_accepted(self):
        result = parse_final_answer("First compute the balance.\nIt is negative.\nFINAL_ANSWER: -6\n")
        self.assertTrue(result.ok)
        self.assertEqual(result.value, -6)
        self.assertEqual(result.code, "ok")

    def test_parser_rejects_invalid_shapes_with_stable_codes(self):
        cases = {
            "": "missing_marker",
            "The marker is FINAL_ANSWER : 3": "marker_like_output",
            "FINAL_ANSWER = 3": "marker_like_output",
            "The final answer is 3": "marker_like_output",
            "FINAL ANSWER: 1\nFINAL_ANSWER: 2": "marker_like_output",
            "FINAL_ANSWER: 1\nFINAL_ANSWER: 2": "duplicate_marker",
            "FINAL_ANSWER:": "empty_answer",
            "FINAL_ANSWER: 1.0": "non_integer_answer",
            "```text\nFINAL_ANSWER: 1\n```": "fenced_output",
            "FINAL_ANSWER: 1```": "fenced_output",
            "FINAL_ANSWER: 1\nadditional prose": "trailing_output",
            "prefix FINAL_ANSWER: 1": "marker_like_output",
        }
        for response, code in cases.items():
            with self.subTest(code=code):
                result = parse_final_answer(response)
                self.assertFalse(result.ok)
                self.assertEqual(result.code, code)
                self.assertIsNone(result.value)

    def test_parser_result_never_reflects_raw_response(self):
        response = "private model output SECRET-123\nFINAL_ANSWER: 4"
        result = parse_final_answer(response)
        rendered = json.dumps(result.to_dict(), sort_keys=True)
        self.assertNotIn("SECRET-123", rendered)
        self.assertNotIn(response, rendered)
        self.assertEqual(set(result.to_dict()), {"ok", "value", "code"})

    def test_marker_constant_is_exact_case_sensitive_protocol(self):
        self.assertEqual(FINAL_ANSWER_MARKER, "FINAL_ANSWER:")
        self.assertFalse(parse_final_answer("final_answer: 4").ok)

    def test_parser_bounds_ascii_integer_digits_without_python_version_dependence(self):
        accepted = parse_final_answer("FINAL_ANSWER: " + ("9" * MAX_INTEGER_DIGITS))
        self.assertTrue(accepted.ok)
        self.assertEqual(
            parse_final_answer("FINAL_ANSWER: -" + ("8" * MAX_INTEGER_DIGITS)).code,
            "ok",
        )
        for answer in (
            "9" * (MAX_INTEGER_DIGITS + 1),
            "+" + ("7" * (MAX_INTEGER_DIGITS + 1)),
            "-" + ("6" * (MAX_INTEGER_DIGITS + 1)),
        ):
            with self.subTest(answer_length=len(answer)):
                result = parse_final_answer("FINAL_ANSWER: " + answer)
                self.assertFalse(result.ok)
                self.assertEqual(result.code, "integer_too_large")


class ReasoningConstraintStressV2CatalogTests(unittest.TestCase):
    def test_catalog_validation_and_evidence_exclusion_identity(self):
        catalog = load_capability_catalog()
        self.assertEqual(validate_benchmark_legitimacy_metadata(catalog), [])
        check = next(
            item for item in catalog["checks"] if item["check_id"] == "reasoning_constraint_stress_v2"
        )
        status = next(
            item
            for item in catalog["benchmark_status_matrix"]
            if item["check_id"] == "reasoning_constraint_stress_v2"
        )
        self.assertTrue(check["canary_only"])
        self.assertEqual(check["allowed_tiers"], ["canary"])
        self.assertEqual(check["attestation_state"], "unreviewed")
        self.assertEqual(check["status"], "canary_only_unreviewed")
        self.assertEqual(status["runnable_status"], "canary_only_unreviewed")
        self.assertEqual(status["maturity"], "planned")
        self.assertEqual(check["fixture_sha256"], FIXTURE_SHA256)
        self.assertEqual(tuple(check["expected_answer_vector"]), EXPECTED_ANSWER_VECTOR)
        self.assertEqual(status["fixture_sha256"], FIXTURE_SHA256)
        self.assertEqual(tuple(status["expected_answer_vector"]), EXPECTED_ANSWER_VECTOR)
        self.assertEqual(status["attestation_state"], "unreviewed")
        self.assertEqual(check["evidence_kind"], "capability")
        self.assertEqual(check["runner_target"], "reasoning_constraint_stress_v2")
        self.assertEqual(check["fixture_revision"], FIXTURE_REVISION)
        self.assertEqual(status["fixture_revision"], FIXTURE_REVISION)
        self.assertEqual(check["selection_digest_algorithm"], SELECTION_DIGEST_ALGORITHM)
        self.assertEqual(status["selection_digest_algorithm"], SELECTION_DIGEST_ALGORITHM)
        self.assertEqual(check["selection_sha256"], SELECTION_DIGEST_SHA256)
        self.assertEqual(status["selection_sha256"], SELECTION_DIGEST_SHA256)
        self.assertEqual(check["score_policy_id"], SCORING_POLICY)
        self.assertEqual(status["scoring_policy_id"], SCORING_POLICY)
        self.assertEqual(check["generation_constraint_id"], FINAL_ANSWER_PARSER_ID)
        self.assertEqual(status["generation_constraint_id"], FINAL_ANSWER_PARSER_ID)
        self.assertEqual(check["generation_policy_id"], "reasoning_constraint_stress_thinking_v2")
        self.assertEqual(status["generation_policy_id"], "reasoning_constraint_stress_thinking_v2")
        self.assertEqual(
            FOUNDATION_CANARY_BENCHMARKS["reasoning_constraint_stress_v2"]["description"],
            FOUNDATION_CANARY_DESCRIPTION,
        )
        self.assertEqual(check["description"], FOUNDATION_CANARY_DESCRIPTION)
        self.assertEqual(check["selection_guidance"], FOUNDATION_CANARY_SELECTION_GUIDANCE)
        self.assertEqual(
            benchmark_evidence_exclusion_reason("reasoning_constraint_stress_v2", catalog),
            "benchmark_canary_only:unreviewed",
        )
        for item in catalog["checks"]:
            if item["check_id"] != "reasoning_constraint_stress_v2":
                continue
            for field in (
                "excluded_from_default_groups",
                "excluded_from_suites",
                "excluded_from_weighted_score",
                "excluded_from_readiness",
                "excluded_from_recommendation",
                "excluded_from_release_evidence",
            ):
                self.assertTrue(item[field])
        self.assertTrue(
            all(
                "reasoning_constraint_stress_v2" not in list(item.get("default_check_ids") or [])
                for item in catalog["benchmark_groups"] + catalog["suites"]
            )
        )
        self.assertTrue(
            all(
                "reasoning_constraint_stress_v2"
                not in list(item.get("check_ids") or []) + list(item.get("default_check_ids") or [])
                for item in catalog["shortcuts"]
            )
        )
        self.assertTrue(
            all(
                "reasoning_constraint_stress_v2"
                not in list(tier_defaults.get("check_ids") or [])
                for use_case_defaults in catalog["legacy_tier_defaults"].values()
                for tier_defaults in use_case_defaults.values()
            )
        )

    def test_code_registered_canary_metadata_mutations_fail_closed(self):
        benchmark_id = "reasoning_constraint_stress_v2"
        exclusion_fields = (
            "excluded_from_default_groups",
            "excluded_from_suites",
            "excluded_from_weighted_score",
            "excluded_from_readiness",
            "excluded_from_recommendation",
            "excluded_from_release_evidence",
        )
        mutations = [
            ("check_canary_missing", lambda check, status: check.pop("canary_only")),
            ("check_canary_false", lambda check, status: check.update(canary_only=False)),
            ("check_canary_zero", lambda check, status: check.update(canary_only=0)),
            ("check_canary_one", lambda check, status: check.update(canary_only=1)),
            ("check_canary_float_one", lambda check, status: check.update(canary_only=1.0)),
            ("check_canary_string", lambda check, status: check.update(canary_only="true")),
            ("status_canary_missing", lambda check, status: status.pop("canary_only")),
            ("status_canary_false", lambda check, status: status.update(canary_only=False)),
            ("status_canary_zero", lambda check, status: status.update(canary_only=0)),
            ("status_canary_one", lambda check, status: status.update(canary_only=1)),
            ("status_canary_float_one", lambda check, status: status.update(canary_only=1.0)),
            ("status_canary_string", lambda check, status: status.update(canary_only="true")),
            ("check_tiers_missing", lambda check, status: check.pop("allowed_tiers")),
            ("check_tiers_broadened", lambda check, status: check.update(allowed_tiers=["canary", "standard"])),
            ("status_tiers_missing", lambda check, status: status.pop("allowed_tiers")),
            ("status_tiers_broadened", lambda check, status: status.update(allowed_tiers=["canary", "gold"])),
            ("status_mismatch", lambda check, status: status.update(canary_only=False)),
            ("status_missing", lambda check, status: status.clear()),
            ("status_non_runnable", lambda check, status: status.update(runnable_status="runnable_intentional_reference")),
            ("status_maturity", lambda check, status: status.update(maturity="thin_local_sample")),
            ("check_attestation_missing", lambda check, status: check.pop("attestation_state")),
            ("check_attestation", lambda check, status: check.update(attestation_state="reviewed")),
            ("status_attestation_missing", lambda check, status: status.pop("attestation_state")),
            ("status_attestation", lambda check, status: status.update(attestation_state="reviewed")),
            ("check_weight_missing", lambda check, status: check.pop("primary_score_weight")),
            ("check_weight_int_zero", lambda check, status: check.update(primary_score_weight=0)),
            ("check_weight_false", lambda check, status: check.update(primary_score_weight=False)),
            ("check_weight_true", lambda check, status: check.update(primary_score_weight=True)),
            ("check_weight_zero", lambda check, status: check.update(primary_score_weight="0")),
            ("check_role_missing", lambda check, status: check.pop("score_role")),
            ("check_role_wrong", lambda check, status: check.update(score_role="headline_component")),
            ("status_default_inclusion", lambda check, status: status.update(default_inclusion_status="available")),
        ]
        mutations.extend(
            ("check_%s_missing" % field, lambda check, status, field=field: check.pop(field))
            for field in exclusion_fields
        )
        mutations.extend(
            ("check_%s_zero" % field, lambda check, status, field=field: check.update({field: 0}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("check_%s_false" % field, lambda check, status, field=field: check.update({field: False}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("check_%s_one" % field, lambda check, status, field=field: check.update({field: 1}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("check_%s_float_one" % field, lambda check, status, field=field: check.update({field: 1.0}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("check_%s_string" % field, lambda check, status, field=field: check.update({field: "true"}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("status_%s_missing" % field, lambda check, status, field=field: status.pop(field))
            for field in exclusion_fields
        )
        mutations.extend(
            ("status_%s_false" % field, lambda check, status, field=field: status.update({field: False}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("status_%s_zero" % field, lambda check, status, field=field: status.update({field: 0}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("status_%s_one" % field, lambda check, status, field=field: status.update({field: 1}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("status_%s_float_one" % field, lambda check, status, field=field: status.update({field: 1.0}))
            for field in exclusion_fields
        )
        mutations.extend(
            ("status_%s_string" % field, lambda check, status, field=field: status.update({field: "true"}))
            for field in exclusion_fields
        )
        mutations.append(
            (
                "check_entry_deleted",
                lambda check, status: check.clear(),
            )
        )
        mutations.extend(
            ("check_%s_wrong" % field, lambda check, status, field=field: check.update({field: "mutated"}))
            for field in (
                "evidence_kind",
                "runner_target",
                "fixture_revision",
                "selection_digest_algorithm",
                "selection_sha256",
                "score_policy_id",
                "generation_constraint_id",
                "generation_policy_id",
                "fixture_sha256",
                "expected_answer_vector",
                "display_name",
                "description",
                "selection_guidance",
                "claim_boundary",
            )
        )
        mutations.extend(
            ("status_%s_wrong" % field, lambda check, status, field=field: status.update({field: "mutated"}))
            for field in (
                "status",
                "evidence_kind",
                "runner_target",
                "fixture_revision",
                "selection_digest_algorithm",
                "selection_sha256",
                "scoring_policy_id",
                "score_policy_id",
                "generation_constraint_id",
                "generation_policy_id",
                "fixture_sha256",
                "expected_answer_vector",
                "claim_boundary",
                "sample_policy",
            )
        )

        for name, mutate in mutations:
            with self.subTest(name=name):
                catalog = deepcopy(load_capability_catalog())
                check = next(item for item in catalog["checks"] if item["check_id"] == benchmark_id)
                status = next(item for item in catalog["benchmark_status_matrix"] if item["check_id"] == benchmark_id)
                mutate(check, status)
                failures = validate_benchmark_legitimacy_metadata(catalog)
                self.assertTrue(any(benchmark_id in failure for failure in failures), failures)
                self.assertEqual(
                    benchmark_evidence_exclusion_reason(benchmark_id, catalog),
                    "benchmark_canary_only:metadata_invalid",
                )
                request = RunRequest(
                    model="fixture",
                    backend="llama.cpp",
                    tier="canary",
                    tier_was_explicit=True,
                    benchmark_check_ids=[benchmark_id],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    r"^benchmark_canary_only:reasoning_constraint_stress_v2:metadata_invalid$",
                ):
                    normalize_request_selection(request, catalog)
                for helper in (
                    capability_benchmark_ids_for_request,
                    deployment_profile_ids_for_request,
                    fidelity_enabled_for_request,
                ):
                    with self.subTest(name=name, helper=helper.__name__):
                        with self.assertRaisesRegex(
                            ValueError,
                            r"^benchmark_canary_only:reasoning_constraint_stress_v2:metadata_invalid$",
                        ):
                            helper(request, catalog)

    def test_selection_metadata_keeps_canary_identity_out_of_evidence_claims(self):
        benchmark_id = "reasoning_constraint_stress_v2"
        identity_request = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="canary",
            tier_was_explicit=True,
            benchmark_check_ids=[benchmark_id],
        )
        metadata = selection_metadata_for_request(identity_request)
        scope = metadata["benchmark_scope"]
        self.assertEqual(scope["scope"], "identity_only")
        self.assertEqual(scope["identity_only_benchmark_check_ids"], [benchmark_id])
        for key in ("evidence_lane_id", "evidence_lane", "claim_strength", "reference_checks_included"):
            self.assertNotIn(key, scope)
        self.assertEqual(metadata["eligible_benchmark_check_ids"], [])
        self.assertEqual(metadata["identity_only_benchmark_check_ids"], [benchmark_id])
        self.assertEqual(metadata["excluded_benchmark_check_ids"], [benchmark_id])
        check_metadata = metadata["benchmark_checks"][0]
        self.assertTrue(check_metadata["identity_only"])
        self.assertIsNone(check_metadata["evidence_lane_id"])
        self.assertIsNone(check_metadata["claim_strength"])
        self.assertIsNone(check_metadata["suite_scope"])
        self.assertEqual(
            capability_coverage_guidance_for_selection([benchmark_id])["selected_reference_check_ids"],
            [],
        )
        self.assertEqual(deployment_profile_ids_for_request(identity_request), [])
        self.assertFalse(fidelity_enabled_for_request(identity_request))

        mixed_request = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="canary",
            tier_was_explicit=True,
            benchmark_check_ids=[benchmark_id, "interactive_chat_v1"],
        )
        mixed = selection_metadata_for_request(mixed_request)
        self.assertEqual(mixed["benchmark_scope"]["scope"], "decision")
        self.assertEqual(mixed["benchmark_scope"]["eligible_benchmark_check_ids"], ["interactive_chat_v1"])
        self.assertEqual(mixed["benchmark_scope"]["excluded_benchmark_check_ids"], [benchmark_id])
        self.assertEqual(mixed["benchmark_scope"]["evidence_lane_id"], "decision")
        mixed_v2 = next(item for item in mixed["benchmark_checks"] if item["check_id"] == benchmark_id)
        self.assertIsNone(mixed_v2["claim_strength"])
        self.assertEqual(mixed_v2["claim_boundary"], FOUNDATION_CANARY_DESCRIPTION)
        self.assertEqual(mixed_v2["benchmark_claim_boundary"], FOUNDATION_CANARY_DESCRIPTION)
        self.assertEqual(mixed["capability_coverage_guidance"]["selected_decision_check_ids"], ["interactive_chat_v1"])
        reference_scope = benchmark_scope_summary_for_selection([benchmark_id, "mmlu_pro_reference_v1"])
        self.assertEqual(reference_scope["scope"], "reference")
        self.assertEqual(reference_scope["eligible_benchmark_check_ids"], ["mmlu_pro_reference_v1"])

    def test_non_explicit_tier_derives_before_canary_restriction(self):
        v2_only = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="standard",
            tier_was_explicit=False,
            benchmark_check_ids=["reasoning_constraint_stress_v2"],
        )
        normalize_request_selection(v2_only)
        self.assertEqual(v2_only.tier, "canary")
        self.assertEqual(capability_benchmark_ids_for_request(v2_only), [])
        self.assertEqual(capability_images_for_request(v2_only), [])

        mixed = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="standard",
            tier_was_explicit=False,
            benchmark_check_ids=["reasoning_constraint_stress_v2", "reasoning_exact_answer_v1"],
        )
        with self.assertRaisesRegex(
            ValueError,
            r"^benchmark_canary_only:reasoning_constraint_stress_v2:tier_not_allowed:(?:standard|gold)$",
        ):
            normalize_request_selection(mixed)

    def test_catalog_rejects_standard_and_gold_after_every_selection_derivation_path(self):
        benchmark_id = "reasoning_constraint_stress_v2"
        catalog = load_capability_catalog()
        group = {
            "group_id": "reasoning_v2_foundation_group",
            "default_check_ids": [benchmark_id],
        }
        mixed_group = {
            "group_id": "reasoning_v2_mixed_group",
            "default_check_ids": [benchmark_id, "reasoning_exact_answer_v1"],
        }
        catalog["benchmark_groups"] = list(catalog["benchmark_groups"]) + [group, mixed_group]
        catalog["suites"] = list(catalog["suites"]) + [
            {
                "suite_id": "reasoning_v2_foundation_suite",
                "default_group_ids": [group["group_id"]],
            }
        ]
        catalog["shortcuts"] = list(catalog["shortcuts"]) + [
            {
                "shortcut_id": "reasoning_v2_foundation_shortcut",
                "check_ids": [benchmark_id],
            }
        ]

        requests = {
            "explicit": RunRequest(
                model="fixture",
                backend="llama.cpp",
                tier="standard",
                tier_was_explicit=True,
                benchmark_check_ids=[benchmark_id],
            ),
            "group": RunRequest(
                model="fixture",
                backend="llama.cpp",
                tier="gold",
                tier_was_explicit=True,
                benchmark_group_ids=[group["group_id"]],
            ),
            "suite": RunRequest(
                model="fixture",
                backend="llama.cpp",
                tier="standard",
                tier_was_explicit=True,
                capability_suite_ids=["reasoning_v2_foundation_suite"],
            ),
            "shortcut": RunRequest(
                model="fixture",
                backend="llama.cpp",
                tier="gold",
                tier_was_explicit=True,
                benchmark_shortcut_id="reasoning_v2_foundation_shortcut",
            ),
            "inferred": RunRequest(
                model="fixture",
                backend="llama.cpp",
                tier="canary",
                tier_was_explicit=False,
                benchmark_group_ids=[mixed_group["group_id"]],
            ),
        }
        for name, request in requests.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError,
                    r"^benchmark_canary_only:reasoning_constraint_stress_v2:metadata_invalid$",
                ):
                    normalize_request_selection(request, catalog)

    def test_foundation_placement_mutations_fail_closed_before_selection(self):
        benchmark_id = "reasoning_constraint_stress_v2"
        mutations = {
            "group_check_ids": lambda catalog: catalog["benchmark_groups"][0].update(
                check_ids=[benchmark_id]
            ),
            "group_default_check_ids": lambda catalog: catalog["benchmark_groups"][0].update(
                default_check_ids=[benchmark_id]
            ),
            "suite_check_ids": lambda catalog: catalog["suites"][0].update(
                check_ids=[benchmark_id]
            ),
            "suite_default_check_ids": lambda catalog: catalog["suites"][0].update(
                default_check_ids=[benchmark_id]
            ),
            "shortcut_check_ids": lambda catalog: catalog["shortcuts"][0].update(
                check_ids=[benchmark_id]
            ),
            "shortcut_default_check_ids": lambda catalog: catalog["shortcuts"][0].update(
                default_check_ids=[benchmark_id]
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                catalog = deepcopy(load_capability_catalog())
                mutate(catalog)
                self.assertEqual(
                    benchmark_evidence_exclusion_reason(benchmark_id, catalog),
                    "benchmark_canary_only:metadata_invalid",
                )
                request = RunRequest(
                    model="fixture",
                    backend="llama.cpp",
                    tier="canary",
                    tier_was_explicit=True,
                    benchmark_check_ids=[benchmark_id],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    r"^benchmark_canary_only:reasoning_constraint_stress_v2:metadata_invalid$",
                ):
                    normalize_request_selection(request, catalog)
                for helper in (
                    benchmark_scope_summary_for_selection,
                    capability_coverage_guidance_for_selection,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        r"^benchmark_canary_only:reasoning_constraint_stress_v2:metadata_invalid$",
                    ):
                        helper([benchmark_id], catalog)

        catalog = deepcopy(load_capability_catalog())
        default_tier = next(iter(catalog["legacy_tier_defaults"].values()))
        default_tier[next(iter(default_tier))]["check_ids"] = [benchmark_id]
        request = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="canary",
            tier_was_explicit=True,
        )
        self.assertEqual(
            benchmark_evidence_exclusion_reason(benchmark_id, catalog),
            "benchmark_canary_only:metadata_invalid",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"^benchmark_canary_only:reasoning_constraint_stress_v2:metadata_invalid$",
        ):
            normalize_request_selection(request, catalog)

    def test_canary_selection_is_identity_only_and_does_not_claim_runtime(self):
        request = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="canary",
            tier_was_explicit=True,
            benchmark_check_ids=["reasoning_constraint_stress_v2"],
        )
        normalize_request_selection(request)
        self.assertEqual(request.benchmark_check_ids, ["reasoning_constraint_stress_v2"])
        self.assertEqual(request.tier, "canary")
        self.assertEqual(capability_benchmark_ids_for_request(request), [])
        self.assertEqual(request.capability, "none")


if __name__ == "__main__":
    unittest.main()
