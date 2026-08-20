import hashlib
import json
import re
import sys
import unittest
from collections import Counter
from copy import deepcopy
from unittest.mock import patch

sys.path.insert(0, "python/runner-core/src")

from infergrade.benchmark_catalog import (  # noqa: E402
    CONTENT_PACK_BENCHMARKS,
    CONTENT_PACK_SELECTION_GUIDANCE,
    CONTENT_PACK_STATUS_BENCHMARKS,
    EXPECTED_CONTENT_PACK_BENCHMARK_IDS,
    benchmark_evidence_exclusion_reason,
    benchmark_scope_summary_for_selection,
    capability_benchmark_ids_for_request,
    capability_coverage_guidance_for_selection,
    load_capability_catalog,
    normalize_request_selection,
    resolve_request_selection,
    selection_metadata_for_request,
    validate_benchmark_legitimacy_metadata,
)
from infergrade.capabilities import CAPABILITY_BENCHMARKS  # noqa: E402
from infergrade.models import RunRequest  # noqa: E402
from infergrade.reasoning_constraint_stress import (  # noqa: E402
    reasoning_constraint_stress_cases as v1_cases,
)
from infergrade.reasoning_constraint_stress_v2 import (  # noqa: E402
    parse_final_answer,
    reasoning_constraint_stress_v2_cases as foundation_cases,
)
from infergrade.reasoning_constraint_stress_v2_content import (  # noqa: E402
    BENCHMARK_ID,
    FAMILY_ORDER,
    FIXTURE_REVISION,
    FIXTURE_SHA256,
    FULL_FIXTURE_SHA256,
    FULL_SELECTION_SHA256,
    GENERATOR_ALGORITHM,
    GENERATOR_ID,
    GENERATOR_REVISION,
    GENERATOR_SEED_SHA256,
    LOCKED_FIXTURE_SHA256,
    LOCKED_FULL_SELECTION_SHA256,
    LOCKED_GENERATOR_SEED_SHA256,
    LOCKED_TIER_COVERAGE,
    LOCKED_TIER_SELECTION_DIGESTS,
    FINAL_ANSWER_MARKER,
    SCORING_POLICY,
    STRUCTURAL_LEVEL_ORDER,
    TIER_COVERAGE,
    TIER_PREFIX_COUNTS,
    TIER_SELECTION_DIGESTS,
    VARIANT_ORDER,
    independent_oracle_answers,
    parse_content_answer,
    reasoning_constraint_stress_v2_content_cases,
    tier_selection_metadata,
)
import infergrade.reasoning_constraint_stress_v2_content as content_module  # noqa: E402
from infergrade.selection_identity import selection_digest  # noqa: E402


class _StringSubclass(str):
    pass


class _StringifiesAs:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value


class _FalsyStringifiesAs(_StringifiesAs):
    def __bool__(self):
        return False


class _StringificationError:
    def __str__(self):
        raise RuntimeError("stringification failed")


class _BooleanError:
    def __bool__(self):
        raise RuntimeError("boolean conversion failed")


class ReasoningConstraintStressV2ContentFixtureTests(unittest.TestCase):
    def test_fixture_is_fresh_40_case_five_family_four_level_two_variant_grid(self):
        cases = reasoning_constraint_stress_v2_content_cases()
        self.assertEqual(FIXTURE_REVISION, "2026-08-reasoning-constraint-stress-v2-content-v1")
        self.assertEqual(SCORING_POLICY, "reasoning_constraint_stress_v2_exact_signed_integer_v1")
        self.assertEqual(len(cases), 40)
        self.assertEqual(len({case["case_id"] for case in cases}), 40)
        self.assertEqual(len({case["task_id"] for case in cases}), 40)
        self.assertEqual(len({case["prompt"] for case in cases}), 40)
        self.assertEqual(Counter(case["category"] for case in cases), {family: 8 for family in FAMILY_ORDER})
        self.assertEqual(
            Counter(case["structural_level"] for case in cases),
            {level: 10 for level in STRUCTURAL_LEVEL_ORDER},
        )
        self.assertEqual(Counter(case["variant"] for case in cases), {variant: 20 for variant in VARIANT_ORDER})
        self.assertEqual(
            {
                (case["category"], case["structural_level"], case["variant"])
                for case in cases
            },
            {
                (family, level, variant)
                for family in FAMILY_ORDER
                for level in STRUCTURAL_LEVEL_ORDER
                for variant in VARIANT_ORDER
            },
        )
        self.assertTrue(all(case["task_id"].startswith(BENCHMARK_ID + "/") for case in cases))
        self.assertTrue(
            set(case["task_id"] for case in cases).isdisjoint(
                item["task_id"] for item in v1_cases()
            )
        )
        self.assertTrue(
            set(case["task_id"] for case in cases).isdisjoint(
                item["task_id"] for item in foundation_cases()
            )
        )
        self.assertTrue(
            set(case["case_id"] for case in cases).isdisjoint(
                item["case_id"] for item in foundation_cases()
            )
        )

    def test_fixture_and_generator_identity_locks_are_exact(self):
        cases = reasoning_constraint_stress_v2_content_cases()
        self.assertEqual(GENERATOR_ID, "sha256_domain_separated_case_generator_v1")
        self.assertEqual(GENERATOR_REVISION, "reasoning_constraint_stress_v2_content_generator_v2")
        self.assertEqual(GENERATOR_ALGORITHM, "sha256_counter_u32_v1")
        self.assertEqual(GENERATOR_SEED_SHA256, LOCKED_GENERATOR_SEED_SHA256)
        self.assertEqual(FIXTURE_SHA256, LOCKED_FIXTURE_SHA256)
        self.assertEqual(FULL_FIXTURE_SHA256, LOCKED_FIXTURE_SHA256)
        self.assertEqual(FULL_SELECTION_SHA256, LOCKED_FULL_SELECTION_SHA256)
        self.assertEqual(TIER_SELECTION_DIGESTS, LOCKED_TIER_SELECTION_DIGESTS)
        self.assertEqual(TIER_COVERAGE, LOCKED_TIER_COVERAGE)
        self.assertEqual(
            hashlib.sha256(
                json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            LOCKED_FIXTURE_SHA256,
        )
        self.assertIs(parse_content_answer, parse_final_answer)
        self.assertEqual(parse_content_answer("FINAL_ANSWER: -3").value, -3)

    def test_prefixes_have_exact_digests_and_coverage_contracts(self):
        cases = reasoning_constraint_stress_v2_content_cases()
        for tier, count in TIER_PREFIX_COUNTS.items():
            prefix = cases[:count]
            self.assertEqual(len(prefix), count)
            self.assertEqual(
                selection_digest(
                    (case["task_id"] for case in prefix),
                    "sorted_json_string_array_sha256_v1",
                ),
                TIER_SELECTION_DIGESTS[tier],
            )
            self.assertEqual(TIER_COVERAGE[tier]["case_count"], count)
            self.assertEqual(
                dict(Counter(case["category"] for case in prefix)),
                TIER_COVERAGE[tier]["family_counts"],
            )
            self.assertEqual(
                dict(Counter(case["structural_level"] for case in prefix)),
                TIER_COVERAGE[tier]["structural_level_counts"],
            )
            self.assertEqual(
                dict(Counter(case["variant"] for case in prefix)),
                TIER_COVERAGE[tier]["variant_counts"],
            )
        self.assertEqual(
            tier_selection_metadata()["gold"]["selection_sha256"],
            FULL_SELECTION_SHA256,
        )
        self.assertEqual(
            TIER_COVERAGE["standard"]["variant_counts"],
            {"alpha": 10, "beta": 10},
        )
        self.assertEqual(
            set(case["structural_level"] for case in cases[:20]),
            set(STRUCTURAL_LEVEL_ORDER),
        )

    def test_independent_family_oracles_match_every_expected_answer(self):
        cases = reasoning_constraint_stress_v2_content_cases()
        oracle_answers = independent_oracle_answers()
        self.assertEqual(set(oracle_answers), {case["task_id"] for case in cases})
        for case in cases:
            with self.subTest(task_id=case["task_id"]):
                self.assertEqual(case["expected_answers"], [oracle_answers[case["task_id"]]])
                self.assertRegex(case["expected_answers"][0], r"^-?[0-9]+$")

    def test_generated_structures_have_duplicate_and_validity_guards(self):
        cases = reasoning_constraint_stress_v2_content_cases()
        for case in cases:
            spec = content_module._CASE_SPECS[case["task_id"]]
            with self.subTest(task_id=case["task_id"]):
                if case["category"] == "constrained_arrangement_count":
                    constraints = spec["constraints"]
                    self.assertEqual(len(constraints), len(set(constraints)))
                    self.assertTrue(content_module._arrangement_valid(spec["target"], constraints))
                if case["category"] == "shortest_route_cost":
                    edges = spec["edges"]
                    self.assertEqual(len(edges), len(set(edges)))
                    self.assertTrue(all(weight > 0 for _, _, weight in edges))
                if case["category"] == "dag_critical_path":
                    positions = {name: index for index, name in enumerate(spec["tasks"])}
                    self.assertTrue(
                        all(
                            positions[parent] < positions[name]
                            for name, task in spec["tasks"].items()
                            for parent in task["dependencies"]
                        )
                    )

    def test_state_cases_require_sequential_state_and_order(self):
        for case in reasoning_constraint_stress_v2_content_cases():
            if case["category"] != "state_reconciliation":
                continue
            spec = content_module._CASE_SPECS[case["task_id"]]
            operations = spec["operations"]
            forward = content_module._state_answer(spec)
            reverse = content_module._state_target(
                content_module._state_apply(
                    spec["x"],
                    spec["y"],
                    spec["z"],
                    tuple(reversed(operations)),
                )
            )
            with self.subTest(task_id=case["task_id"]):
                self.assertNotEqual(forward, spec["x"] + spec["y"])
                self.assertNotEqual(forward, reverse)
                self.assertEqual(
                    forward,
                    content_module._state_independent_answer(spec),
                )
                self.assertTrue(any(op[0].startswith("assign_") for op in operations))
                self.assertTrue(any(op[0] == "assign_z_product_mod" for op in operations))

    def test_dags_have_parallel_nonredundant_structure(self):
        for case in reasoning_constraint_stress_v2_content_cases():
            if case["category"] != "dag_critical_path":
                continue
            spec = content_module._CASE_SPECS[case["task_id"]]
            tasks = spec["tasks"]
            outgoing = {name: set() for name in tasks}
            edges = []
            for child, task in tasks.items():
                for parent in task["dependencies"]:
                    outgoing[parent].add(child)
                    edges.append((parent, child))

            def reachable(start, target, omitted):
                pending = [start]
                seen = {start}
                while pending:
                    parent = pending.pop()
                    for child in outgoing[parent]:
                        if (parent, child) == omitted or child in seen:
                            continue
                        if child == target:
                            return True
                        seen.add(child)
                        pending.append(child)
                return False

            roots = [name for name, task in tasks.items() if not task["dependencies"]]
            terminal_layer = set(spec["layers"][-1])
            with self.subTest(task_id=case["task_id"]):
                self.assertGreaterEqual(len(roots), 2)
                self.assertTrue(any(len(children) >= 2 for children in outgoing.values()))
                self.assertTrue(any(len(task["dependencies"]) >= 2 for task in tasks.values()))
                self.assertTrue(
                    all(outgoing[name] for name in tasks if name not in terminal_layer)
                )
                self.assertLess(
                    content_module._dag_answer(spec),
                    sum(task["duration"] for task in tasks.values()),
                )
                for edge in edges:
                    self.assertFalse(reachable(edge[0], edge[1], edge), edge)

    def test_structural_difficulty_scales_by_level(self):
        cases = reasoning_constraint_stress_v2_content_cases()

        def values(family, metric):
            return [
                min(
                    metric(content_module._CASE_SPECS[case["task_id"]])
                    for case in cases
                    if case["category"] == family
                    and case["structural_level"] == level
                )
                for level in STRUCTURAL_LEVEL_ORDER
            ]

        state_ops = values("state_reconciliation", lambda spec: len(spec["operations"]))
        route_nodes = values("shortest_route_cost", lambda spec: len(spec["nodes"]))
        dag_tasks = values("dag_critical_path", lambda spec: len(spec["tasks"]))
        dag_depth = values("dag_critical_path", lambda spec: len(spec["layers"]))
        dag_edges = values(
            "dag_critical_path",
            lambda spec: sum(len(task["dependencies"]) for task in spec["tasks"].values()),
        )
        set_count = values("set_cardinality", lambda spec: spec["set_count"])
        set_universe = values("set_cardinality", lambda spec: spec["universe"])
        arrangement_items = values(
            "constrained_arrangement_count", lambda spec: len(spec["items"])
        )
        arrangement_constraints = values(
            "constrained_arrangement_count", lambda spec: len(spec["constraints"])
        )
        for metric in (
            state_ops,
            route_nodes,
            dag_tasks,
            dag_depth,
            dag_edges,
            set_count,
            set_universe,
            arrangement_items,
            arrangement_constraints,
        ):
            self.assertTrue(all(left < right for left, right in zip(metric, metric[1:])), metric)

    def test_arrangement_independent_oracle_has_separate_semantics(self):
        semantic_cases = (
            ({"items": ("A", "B", "C"), "constraints": (("before", "A", "B"),)}, 3),
            ({"items": ("A", "B", "C"), "constraints": (("adjacent", "A", "B"),)}, 4),
            ({"items": ("A", "B", "C"), "constraints": (("fixed", "A", 1),)}, 2),
            (
                {"items": ("A", "B", "C"), "constraints": (("not_adjacent", "A", "B"),)},
                2,
            ),
        )
        for spec, expected in semantic_cases:
            with self.subTest(constraint=spec["constraints"][0][0]):
                self.assertEqual(content_module._arrangement_answer(spec), expected)
                self.assertEqual(content_module._arrangement_independent_answer(spec), expected)

        arrangement_case = next(
            case
            for case in reasoning_constraint_stress_v2_content_cases()
            if case["category"] == "constrained_arrangement_count"
        )
        original = content_module._CASE_SPECS[arrangement_case["task_id"]]
        expected = content_module._arrangement_independent_answer(original)
        with patch.object(
            content_module,
            "_arrangement_valid",
            side_effect=AssertionError("shared validator must not be called"),
        ):
            self.assertEqual(content_module._arrangement_independent_answer(original), expected)

        impossible = deepcopy(original)
        item = impossible["items"][0]
        impossible["constraints"] = impossible["constraints"] + (
            ("fixed", item, 1),
            ("fixed", item, 2),
        )
        self.assertEqual(content_module._arrangement_answer(impossible), 0)
        self.assertEqual(content_module._arrangement_independent_answer(impossible), 0)

    def test_prompts_have_no_answer_or_protocol_shortcuts(self):
        cases = reasoning_constraint_stress_v2_content_cases()
        standalone_integer = re.compile(r"(?<![A-Za-z0-9_])[+-]?\d+(?![A-Za-z0-9_])")
        for case in cases:
            prompt = case["prompt"]
            answer = case["expected_answers"][0]
            input_numbers = {
                int(match.group()) for match in standalone_integer.finditer(prompt)
            }
            with self.subTest(task_id=case["task_id"]):
                self.assertEqual(prompt.count(FINAL_ANSWER_MARKER), 1)
                self.assertNotIn("The answer is", prompt)
                self.assertNotIn("answer equals", prompt.lower())
                self.assertNotIn("%s %s" % (FINAL_ANSWER_MARKER, answer), prompt)
                self.assertNotIn('"expected_answers"', prompt)
                self.assertNotIn("oracle", prompt.lower())
                self.assertNotIn(int(answer), input_numbers)

    def test_set_union_cases_do_not_trivially_equal_the_universe(self):
        for case in reasoning_constraint_stress_v2_content_cases():
            if case["category"] != "set_cardinality":
                continue
            spec = content_module._CASE_SPECS[case["task_id"]]
            if spec["query"] != "union":
                continue
            with self.subTest(task_id=case["task_id"]):
                self.assertLess(int(case["expected_answers"][0]), spec["universe"])

    def test_returned_cases_are_fresh_and_mutation_does_not_change_identity(self):
        first = reasoning_constraint_stress_v2_content_cases()
        first[0]["prompt"] = "tampered"
        first[0]["expected_answers"].append("999")
        second = reasoning_constraint_stress_v2_content_cases()
        self.assertNotEqual(second[0]["prompt"], "tampered")
        self.assertEqual(len(second[0]["expected_answers"]), 1)
        self.assertEqual(
            hashlib.sha256(
                json.dumps(second, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            LOCKED_FIXTURE_SHA256,
        )


class ReasoningConstraintStressV2ContentCatalogTests(unittest.TestCase):
    def test_content_identity_is_planned_and_absent_from_execution_registry(self):
        catalog = load_capability_catalog()
        self.assertEqual(EXPECTED_CONTENT_PACK_BENCHMARK_IDS, {BENCHMARK_ID})
        self.assertEqual(set(CONTENT_PACK_BENCHMARKS), {BENCHMARK_ID})
        self.assertEqual(set(CONTENT_PACK_STATUS_BENCHMARKS), {BENCHMARK_ID})
        self.assertIn(BENCHMARK_ID, CONTENT_PACK_BENCHMARKS)
        self.assertNotIn(BENCHMARK_ID, CAPABILITY_BENCHMARKS)
        check = next(item for item in catalog["checks"] if item["check_id"] == BENCHMARK_ID)
        status = next(item for item in catalog["benchmark_status_matrix"] if item["check_id"] == BENCHMARK_ID)
        self.assertEqual(check["status"], "planned")
        self.assertEqual(status["runnable_status"], "not_runnable")
        self.assertEqual(status["maturity"], "planned")
        self.assertIs(check["identity_only"], True)
        self.assertIs(status["identity_only"], True)
        self.assertIsNone(check["group_id"])
        self.assertIsNone(status["group_id"])
        for payload in (check, status):
            for field in (
                "excluded_from_default_groups",
                "excluded_from_suites",
                "excluded_from_weighted_score",
                "excluded_from_readiness",
                "excluded_from_recommendation",
                "excluded_from_release_evidence",
            ):
                self.assertIs(payload[field], True)
        self.assertTrue(
            all(
                BENCHMARK_ID not in list(item.get("check_ids") or []) + list(item.get("default_check_ids") or [])
                for item in catalog["benchmark_groups"] + catalog["suites"] + catalog["shortcuts"]
            )
        )
        self.assertTrue(
            all(
                BENCHMARK_ID not in list(tier_defaults.get("check_ids") or [])
                for use_case_defaults in catalog["legacy_tier_defaults"].values()
                for tier_defaults in use_case_defaults.values()
            )
        )
        self.assertEqual(validate_benchmark_legitimacy_metadata(catalog), [])
        self.assertEqual(
            benchmark_evidence_exclusion_reason(BENCHMARK_ID, catalog),
            "benchmark_identity_only:planned",
        )

    def test_content_identity_can_be_inspected_without_an_evidence_lane(self):
        request = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="standard",
            tier_was_explicit=True,
            benchmark_check_ids=[BENCHMARK_ID],
        )
        scope = benchmark_scope_summary_for_selection([BENCHMARK_ID])
        self.assertEqual(scope["scope"], "identity_only")
        self.assertEqual(scope["identity_only_benchmark_check_ids"], [BENCHMARK_ID])
        self.assertEqual(scope["selection_guidance"], CONTENT_PACK_SELECTION_GUIDANCE)
        self.assertNotIn("claim_strength", scope)
        self.assertNotIn("evidence_lane_id", scope)
        self.assertEqual(capability_benchmark_ids_for_request(request), [])
        normalized = normalize_request_selection(request)
        self.assertEqual(normalized.capability, "none")
        self.assertEqual(normalized.benchmark_group_ids, [])

        guidance = capability_coverage_guidance_for_selection([BENCHMARK_ID])
        planned_ids = {
            item["check_id"] for item in guidance["planned_benchmark_candidates"]
        }
        self.assertNotIn(BENCHMARK_ID, planned_ids)
        self.assertEqual(guidance["eligible_benchmark_check_ids"], [])
        self.assertEqual(guidance["selected_evidence_lane_ids"], [])

        metadata = selection_metadata_for_request(request)
        self.assertEqual(metadata["benchmark_group_ids"], [])
        self.assertEqual(metadata["score_policies"], [])
        check_metadata = metadata["benchmark_checks"][0]
        self.assertIs(check_metadata["identity_only"], True)
        self.assertIsNone(check_metadata["group_id"])
        self.assertIsNone(check_metadata["evidence_lane_id"])
        self.assertIsNone(check_metadata["suite_scope"])
        self.assertEqual(
            check_metadata["selection_guidance"],
            CONTENT_PACK_SELECTION_GUIDANCE,
        )

        mixed_scope = benchmark_scope_summary_for_selection([BENCHMARK_ID, "ifeval"])
        self.assertEqual(mixed_scope["scope"], "decision")
        self.assertEqual(mixed_scope["eligible_benchmark_check_ids"], ["ifeval"])
        self.assertEqual(mixed_scope["identity_only_benchmark_check_ids"], [BENCHMARK_ID])

    def test_registry_and_catalog_mutations_fail_closed(self):
        base = load_capability_catalog()
        mutations = (
            ("check_fixture", lambda check, status: check.update(fixture_sha256="0" * 64)),
            ("check_seed", lambda check, status: check.update(generator_seed_sha256="0" * 64)),
            ("check_tier_digest", lambda check, status: check["tier_selection_digests"].update(canary="0" * 64)),
            ("status_coverage", lambda check, status: status["tier_coverage"]["gold"].update(case_count=39)),
            ("nested_bool", lambda check, status: check["tier_coverage"]["canary"].update(case_count=True)),
            ("check_identity", lambda check, status: check.update(identity_only=False)),
            ("status_identity", lambda check, status: status.update(identity_only=False)),
            ("runner_target", lambda check, status: check.update(runner_target="reasoning_constraint_stress_v2")),
            ("group_id", lambda check, status: status.update(group_id="reasoning")),
            ("execution_pattern", lambda check, status: check.update(execution_pattern="container_batch")),
            ("check_status", lambda check, status: check.update(status="available")),
            ("status_runnable", lambda check, status: status.update(runnable_status="runnable_intentional_reference")),
            ("default_status", lambda check, status: check.update(default_inclusion_status="not_quick_default")),
            ("maturity", lambda check, status: status.update(maturity="reference_runnable")),
            ("attestation", lambda check, status: check.update(attestation_state="reviewed")),
            ("evidence_kind", lambda check, status: status.update(evidence_kind="diagnostic")),
            ("suite_scope", lambda check, status: check.update(suite_scope="decision")),
            ("evidence_lane", lambda check, status: status.update(evidence_lane_id="decision")),
            ("parser", lambda check, status: check.update(generation_constraint_id="free_text_v1")),
            ("generation_policy", lambda check, status: status.update(generation_policy_id="default_v1")),
            ("exclusion", lambda check, status: check.update(excluded_from_readiness=False)),
            ("score_weight_bool", lambda check, status: status.update(primary_score_weight=True)),
            ("score_role", lambda check, status: check.update(score_role="primary")),
            ("extra_metadata", lambda check, status: check.update(runnable=True)),
            ("placement", lambda check, status: None),
            ("tuple_placement", lambda check, status: None),
            ("coverage_priority", lambda check, status: None),
            ("representativeness_support", lambda check, status: None),
            ("planned_recommendation", lambda check, status: None),
            ("unknown_nested_value", lambda check, status: None),
            ("unknown_nested_key", lambda check, status: None),
            ("padded_list", lambda check, status: None),
            ("padded_tuple", lambda check, status: None),
            ("padded_dict_key", lambda check, status: None),
            ("padded_default", lambda check, status: None),
            ("padded_unknown", lambda check, status: None),
            ("padded_check_id", lambda check, status: check.update(check_id=" %s " % BENCHMARK_ID)),
            ("padded_runner_target", lambda check, status: status.update(runner_target=" %s " % BENCHMARK_ID)),
            ("duplicate_check_clean", lambda check, status: None),
            ("duplicate_check_mutated", lambda check, status: None),
            ("duplicate_status_clean", lambda check, status: None),
            ("duplicate_status_mutated", lambda check, status: None),
            ("delete_check", lambda check, status: None),
            ("delete_status", lambda check, status: None),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                catalog = deepcopy(base)
                check = next(item for item in catalog["checks"] if item["check_id"] == BENCHMARK_ID)
                status = next(item for item in catalog["benchmark_status_matrix"] if item["check_id"] == BENCHMARK_ID)
                if name == "placement":
                    catalog["benchmark_groups"][0]["check_ids"] = [BENCHMARK_ID]
                elif name == "tuple_placement":
                    catalog["benchmark_groups"][0]["check_ids"] = (BENCHMARK_ID,)
                elif name == "coverage_priority":
                    catalog["coverage_expansion_priorities"][0][
                        "benchmark_check_ids"
                    ].append(BENCHMARK_ID)
                elif name == "representativeness_support":
                    catalog["surface_score_policies"][0]["representativeness_policy"][
                        "supporting_check_ids"
                    ].append(BENCHMARK_ID)
                elif name == "planned_recommendation":
                    catalog["planned_benchmark_candidates"].append(
                        {"check_id": BENCHMARK_ID}
                    )
                elif name == "unknown_nested_value":
                    catalog["unknown_extension"] = {
                        "nested": ({"identity": BENCHMARK_ID},)
                    }
                elif name == "unknown_nested_key":
                    catalog["unknown_extension"] = {BENCHMARK_ID: "nested_key"}
                elif name == "padded_list":
                    catalog["benchmark_groups"][0]["check_ids"] = [
                        " %s " % BENCHMARK_ID
                    ]
                elif name == "padded_tuple":
                    catalog["benchmark_groups"][0]["check_ids"] = (
                        "\t%s\n" % BENCHMARK_ID,
                    )
                elif name == "padded_dict_key":
                    catalog["unknown_extension"] = {
                        " %s " % BENCHMARK_ID: "nested_key"
                    }
                elif name == "padded_default":
                    catalog["benchmark_groups"][0]["default_check_ids"] = [
                        " %s " % BENCHMARK_ID
                    ]
                elif name == "padded_unknown":
                    catalog["unknown_extension"] = {
                        "nested": ["\t%s\n" % BENCHMARK_ID]
                    }
                elif name == "duplicate_check_clean":
                    catalog["checks"].append(deepcopy(check))
                elif name == "duplicate_check_mutated":
                    duplicate = deepcopy(check)
                    duplicate["status"] = "available"
                    catalog["checks"].append(duplicate)
                elif name == "duplicate_status_clean":
                    catalog["benchmark_status_matrix"].append(deepcopy(status))
                elif name == "duplicate_status_mutated":
                    duplicate = deepcopy(status)
                    duplicate["runnable_status"] = "runnable_intentional_reference"
                    catalog["benchmark_status_matrix"].append(duplicate)
                elif name == "delete_check":
                    catalog["checks"] = [
                        item for item in catalog["checks"] if item["check_id"] != BENCHMARK_ID
                    ]
                elif name == "delete_status":
                    catalog["benchmark_status_matrix"] = [
                        item
                        for item in catalog["benchmark_status_matrix"]
                        if item["check_id"] != BENCHMARK_ID
                    ]
                else:
                    mutate(check, status)
                failures = validate_benchmark_legitimacy_metadata(catalog)
                self.assertTrue(any(BENCHMARK_ID in failure for failure in failures), failures)
                self.assertEqual(
                    benchmark_evidence_exclusion_reason(BENCHMARK_ID, catalog),
                    "benchmark_identity_only:metadata_invalid",
                )
                with self.assertRaisesRegex(
                    ValueError,
                    r"^benchmark_identity_only:reasoning_constraint_stress_v2_content_v1:metadata_invalid$",
                ):
                    normalize_request_selection(
                        RunRequest(
                            model="fixture",
                            backend="llama.cpp",
                            tier="standard",
                            tier_was_explicit=True,
                            benchmark_check_ids=[BENCHMARK_ID],
                        ),
                        catalog,
                    )

    def test_padded_group_default_cannot_normalize_into_content_selection(self):
        catalog = load_capability_catalog()
        group = catalog["benchmark_groups"][0]
        group["default_check_ids"] = [" %s " % BENCHMARK_ID]
        with self.assertRaisesRegex(
            ValueError,
            r"^benchmark_identity_only:reasoning_constraint_stress_v2_content_v1:metadata_invalid$",
        ):
            resolve_request_selection(
                RunRequest(
                    model="fixture",
                    backend="llama.cpp",
                    tier="standard",
                    tier_was_explicit=True,
                    benchmark_group_ids=[group["group_id"]],
                ),
                catalog,
            )

    def test_non_string_defaults_cannot_normalize_into_content_selection(self):
        values = (
            _StringSubclass(" %s " % BENCHMARK_ID),
            _StringifiesAs("\t%s\n" % BENCHMARK_ID),
        )
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                catalog = load_capability_catalog()
                group = catalog["benchmark_groups"][0]
                group["default_check_ids"] = [value]
                with self.assertRaisesRegex(
                    ValueError,
                    r"^benchmark_identity_only:reasoning_constraint_stress_v2_content_v1:metadata_invalid$",
                ):
                    resolve_request_selection(
                        RunRequest(
                            model="fixture",
                            backend="llama.cpp",
                            tier="standard",
                            tier_was_explicit=True,
                            benchmark_group_ids=[group["group_id"]],
                        ),
                        catalog,
                    )

    def test_scalar_stringification_errors_fail_closed(self):
        for value in (_StringificationError(), _BooleanError()):
            with self.subTest(value_type=type(value).__name__):
                catalog = load_capability_catalog()
                catalog["unknown_extension"] = {"value": value}
                self.assertEqual(
                    benchmark_evidence_exclusion_reason(BENCHMARK_ID, catalog),
                    "benchmark_identity_only:metadata_invalid",
                )
                failures = validate_benchmark_legitimacy_metadata(catalog)
                self.assertTrue(any(BENCHMARK_ID in failure for failure in failures), failures)

    def test_falsy_custom_scalar_matches_selection_empty_normalization(self):
        catalog = load_capability_catalog()
        group = catalog["benchmark_groups"][0]
        group["default_check_ids"] = [
            _FalsyStringifiesAs(" %s " % BENCHMARK_ID)
        ]
        self.assertEqual(
            benchmark_evidence_exclusion_reason(BENCHMARK_ID, catalog),
            "benchmark_identity_only:planned",
        )
        selection = resolve_request_selection(
            RunRequest(
                model="fixture",
                backend="llama.cpp",
                tier="standard",
                tier_was_explicit=True,
                benchmark_group_ids=[group["group_id"]],
            ),
            catalog,
        )
        self.assertNotIn(BENCHMARK_ID, selection["check_ids"])

    def test_ordinary_integer_and_boolean_defaults_do_not_false_match(self):
        catalog = load_capability_catalog()
        group = catalog["benchmark_groups"][0]
        group["default_check_ids"] = [0, 1, False, True]
        self.assertEqual(
            benchmark_evidence_exclusion_reason(BENCHMARK_ID, catalog),
            "benchmark_identity_only:planned",
        )
        selection = resolve_request_selection(
            RunRequest(
                model="fixture",
                backend="llama.cpp",
                tier="standard",
                tier_was_explicit=True,
                benchmark_group_ids=[group["group_id"]],
            ),
            catalog,
        )
        self.assertNotIn(BENCHMARK_ID, selection["check_ids"])

    def test_registry_deletion_cannot_disable_known_identity_exclusion(self):
        catalog = load_capability_catalog()
        registry_mutations = (
            ("check_registry_deleted", CONTENT_PACK_BENCHMARKS, {}, True),
            ("status_registry_deleted", CONTENT_PACK_STATUS_BENCHMARKS, {}, True),
            (
                "unexpected_registry_identity",
                CONTENT_PACK_BENCHMARKS,
                {"unexpected_content_identity": {}},
                False,
            ),
        )
        for name, registry, values, clear in registry_mutations:
            with self.subTest(name=name), patch.dict(registry, values, clear=clear):
                self.assertEqual(
                    benchmark_evidence_exclusion_reason(BENCHMARK_ID, catalog),
                    "benchmark_identity_only:metadata_invalid",
                )
                failures = validate_benchmark_legitimacy_metadata(catalog)
                self.assertTrue(any(BENCHMARK_ID in failure for failure in failures), failures)
                with self.assertRaisesRegex(
                    ValueError,
                    r"^benchmark_identity_only:reasoning_constraint_stress_v2_content_v1:metadata_invalid$",
                ):
                    normalize_request_selection(
                        RunRequest(
                            model="fixture",
                            backend="llama.cpp",
                            tier="standard",
                            tier_was_explicit=True,
                            benchmark_check_ids=[BENCHMARK_ID],
                        ),
                        catalog,
                    )


if __name__ == "__main__":
    unittest.main()
