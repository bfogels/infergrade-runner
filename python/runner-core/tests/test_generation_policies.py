import hashlib
import json
import sys
import unittest
from dataclasses import FrozenInstanceError, replace

sys.path.insert(0, "python/runner-core/src")

from infergrade.capabilities import CAPABILITY_BENCHMARKS
from infergrade.generation_policies import (
    CANONICAL_POLICY_FIELDS,
    DEFAULT_GENERATION_POLICY_ID,
    DIRECT_ANSWER_GENERATION_POLICY_ID,
    GENERATION_POLICY_REGISTRY,
    REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID,
    UnknownGenerationPolicyError,
    resolve_generation_policy,
)


class GenerationPolicyTests(unittest.TestCase):
    def test_registry_resolves_exact_policies_and_default(self):
        self.assertIs(resolve_generation_policy(), GENERATION_POLICY_REGISTRY[DEFAULT_GENERATION_POLICY_ID])
        self.assertIs(
            resolve_generation_policy(DEFAULT_GENERATION_POLICY_ID),
            GENERATION_POLICY_REGISTRY[DEFAULT_GENERATION_POLICY_ID],
        )
        direct = resolve_generation_policy(DIRECT_ANSWER_GENERATION_POLICY_ID)
        self.assertEqual(direct.thinking_mode, "disabled")
        self.assertFalse(direct.enable_thinking)
        self.assertEqual(direct.thinking_budget_tokens, 0)
        self.assertIsNone(direct.max_output_tokens)
        self.assertIsNone(direct.max_output_token_cap)
        self.assertFalse(direct.cache_prompt)
        self.assertEqual(direct.chat_template_kwargs, (("enable_thinking", False),))
        stress = resolve_generation_policy(REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID)
        self.assertEqual(stress.thinking_mode, "enabled")
        self.assertTrue(stress.enable_thinking)
        self.assertEqual(stress.thinking_budget_tokens, 256)
        self.assertEqual(stress.max_output_tokens, 512)
        self.assertEqual(stress.max_output_token_cap, 512)
        self.assertEqual(stress.protocol_version, "generation_protocol_v2")
        self.assertEqual(stress.terminal_answer_marker, "FINAL_ANSWER:")
        self.assertEqual(stress.terminal_answer_format, "integer")
        self.assertEqual(stress.terminal_parser_id, "final_answer_integer_v1")
        self.assertEqual(stress.stop_semantics_version, "natural_or_budget_v1")

    def test_cross_benchmark_policies_defer_variable_catalog_budgets_and_caps(self):
        observed_budgets = {
            benchmark_id: CAPABILITY_BENCHMARKS[benchmark_id].generation_max_tokens
            for benchmark_id in (
                "reasoning_exact_answer_v1",
                "ifeval",
                "repository_edit_smoke_v1",
            )
        }
        self.assertEqual(
            observed_budgets,
            {
                "reasoning_exact_answer_v1": 32,
                "ifeval": 640,
                "repository_edit_smoke_v1": 1024,
            },
        )
        for policy_id in (
            DEFAULT_GENERATION_POLICY_ID,
            DIRECT_ANSWER_GENERATION_POLICY_ID,
        ):
            with self.subTest(policy_id=policy_id):
                policy = resolve_generation_policy(policy_id)
                self.assertIsNone(policy.max_output_tokens)
                self.assertIsNone(policy.max_output_token_cap)

    def test_fixed_budget_requires_a_non_null_cap_and_cannot_exceed_it(self):
        stress = resolve_generation_policy(REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID)
        with self.assertRaises(ValueError):
            replace(stress, max_output_token_cap=None)
        with self.assertRaises(ValueError):
            replace(stress, max_output_token_cap=256)

    def test_unknown_and_empty_policy_ids_fail_closed(self):
        for policy_id in ("does_not_exist", "", " deterministic_v1", 1):
            with self.subTest(policy_id=policy_id):
                with self.assertRaises(UnknownGenerationPolicyError):
                    resolve_generation_policy(policy_id)

    def test_unhashable_thinking_modes_fail_with_value_error(self):
        policy = resolve_generation_policy(DEFAULT_GENERATION_POLICY_ID)
        for malformed in ([], {}, ["default"]):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    replace(policy, thinking_mode=malformed)

    def test_thinking_controls_reject_conflicts_and_invalid_types(self):
        default = resolve_generation_policy(DEFAULT_GENERATION_POLICY_ID)
        direct = resolve_generation_policy(DIRECT_ANSWER_GENERATION_POLICY_ID)
        stress = resolve_generation_policy(REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID)

        for malformed in (0, 1, "true", [], {}):
            with self.subTest(top_level_enable_thinking=malformed):
                with self.assertRaises(ValueError):
                    replace(default, enable_thinking=malformed)
        for malformed in (0, 1, "true", [], {}):
            with self.subTest(chat_template_enable_thinking=malformed):
                with self.assertRaises(ValueError):
                    replace(stress, chat_template_kwargs=(("enable_thinking", malformed),))

        with self.assertRaises(ValueError):
            replace(stress, chat_template_kwargs=(("enable_thinking", False),))
        with self.assertRaises(ValueError):
            replace(default, thinking_budget_tokens=1)
        with self.assertRaises(ValueError):
            replace(direct, thinking_budget_tokens=1)
        with self.assertRaises(ValueError):
            replace(stress, thinking_budget_tokens=513)
        with self.assertRaises(ValueError):
            replace(stress, max_output_tokens=None, thinking_budget_tokens=513)

    def test_terminal_protocol_fields_fail_closed_as_one_tuple(self):
        default = resolve_generation_policy(DEFAULT_GENERATION_POLICY_ID)
        stress = resolve_generation_policy(REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID)

        inconsistent_changes = (
            (default, {"terminal_answer_marker": "FINAL_ANSWER:"}),
            (default, {"terminal_answer_format": "integer"}),
            (default, {"terminal_parser_id": "final_answer_integer_v1"}),
            (stress, {"terminal_answer_marker": None}),
            (stress, {"terminal_answer_format": None}),
            (stress, {"terminal_parser_id": "none_v1"}),
        )
        for policy, changes in inconsistent_changes:
            with self.subTest(policy_id=policy.policy_id, changes=changes):
                with self.assertRaises(ValueError):
                    replace(policy, **changes)

        malformed_changes = (
            {"terminal_answer_marker": []},
            {"terminal_answer_marker": {}},
            {"terminal_answer_format": []},
            {"terminal_answer_format": {}},
            {"terminal_parser_id": []},
            {"terminal_parser_id": {}},
        )
        for changes in malformed_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(stress, **changes)

    def test_policy_and_registry_are_immutable(self):
        policy = resolve_generation_policy(DIRECT_ANSWER_GENERATION_POLICY_ID)
        with self.assertRaises(FrozenInstanceError):
            policy.seed = 99
        with self.assertRaises(TypeError):
            GENERATION_POLICY_REGISTRY["new_policy"] = policy
        with self.assertRaises(TypeError):
            policy.chat_template_kwargs[0][1] = True

        payload = policy.to_dict()
        payload["chat_template_kwargs"]["enable_thinking"] = True
        self.assertEqual(policy.chat_template_kwargs, (("enable_thinking", False),))

    def test_fingerprints_are_stable_and_are_sha256(self):
        policy = resolve_generation_policy(DEFAULT_GENERATION_POLICY_ID)
        expected = hashlib.sha256(policy.canonical_json().encode("utf-8")).hexdigest()
        self.assertEqual(policy.fingerprint_sha256, expected)
        self.assertEqual(policy.fingerprint, expected)
        self.assertEqual(len(expected), 64)
        self.assertEqual(expected, resolve_generation_policy(DEFAULT_GENERATION_POLICY_ID).fingerprint_sha256)

    def test_fingerprint_changes_when_a_canonical_field_changes(self):
        policy = resolve_generation_policy(DEFAULT_GENERATION_POLICY_ID)
        for field, value in (
            ("seed", 1),
            ("protocol_version", "generation_protocol_test_v1"),
            ("cache_prompt", True),
            ("prompt_transform_id", "changed_v1"),
            ("stop_semantics_version", "changed_v1"),
        ):
            with self.subTest(field=field):
                changed = replace(policy, **{field: value})
                self.assertNotEqual(policy.fingerprint_sha256, changed.fingerprint_sha256)
                self.assertNotEqual(policy.canonical_json(), changed.canonical_json())

        stress = resolve_generation_policy(REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID)
        changed_cap = replace(stress, max_output_token_cap=1024)
        self.assertNotEqual(stress.fingerprint_sha256, changed_cap.fingerprint_sha256)
        changed_terminal = replace(
            stress,
            terminal_answer_marker=None,
            terminal_answer_format=None,
            terminal_parser_id="none_v1",
        )
        self.assertNotEqual(stress.fingerprint_sha256, changed_terminal.fingerprint_sha256)
        changed_thinking = replace(
            stress,
            enable_thinking=False,
            thinking_mode="disabled",
            thinking_budget_tokens=0,
            chat_template_kwargs=(("enable_thinking", False),),
        )
        self.assertNotEqual(stress.fingerprint_sha256, changed_thinking.fingerprint_sha256)

    def test_canonical_serialization_is_sorted_compact_and_complete(self):
        policy = resolve_generation_policy(REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID)
        payload = policy.to_dict()
        self.assertEqual(tuple(payload), CANONICAL_POLICY_FIELDS)
        expected = json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(policy.canonical_json(), expected)
        self.assertEqual(json.loads(policy.canonical_json()), payload)
        self.assertNotIn("fingerprint", payload)
        self.assertNotIn("fingerprint_sha256", payload)

    def test_golden_canonical_json_and_sha256_vectors(self):
        expected = {
            "deterministic_v1": (
                '{"cache_prompt":false,"chat_template_kwargs":{},"enable_thinking":null,"max_output_token_cap":null,"max_output_tokens":null,"policy_id":"deterministic_v1","policy_revision":"generation_policy_v1","prompt_directive":null,"prompt_transform_id":"none_v1","protocol_version":"generation_protocol_v1","seed":0,"stop_semantics_version":"backend_stop_v1","temperature":0.0,"terminal_answer_format":null,"terminal_answer_marker":null,"terminal_parser_id":"none_v1","thinking_budget_tokens":0,"thinking_mode":"default","top_p":1.0}',
                "5821bccd926c346b29c0d6d3d72937efa3a6d56eed09b5486fac0c403aae9cfd",
            ),
            "deterministic_direct_answer_v1": (
                '{"cache_prompt":false,"chat_template_kwargs":{"enable_thinking":false},"enable_thinking":false,"max_output_token_cap":null,"max_output_tokens":null,"policy_id":"deterministic_direct_answer_v1","policy_revision":"generation_policy_v1","prompt_directive":"/no_think","prompt_transform_id":"direct_answer_model_aware_v2","protocol_version":"generation_protocol_v1","seed":0,"stop_semantics_version":"backend_stop_v1","temperature":0.0,"terminal_answer_format":null,"terminal_answer_marker":null,"terminal_parser_id":"none_v1","thinking_budget_tokens":0,"thinking_mode":"disabled","top_p":1.0}',
                "205530a73d357dbb0ba4b82fd670d1473134957799c5bed193d09d43cd661b41",
            ),
            "reasoning_constraint_stress_thinking_v2": (
                '{"cache_prompt":false,"chat_template_kwargs":{"enable_thinking":true},"enable_thinking":true,"max_output_token_cap":512,"max_output_tokens":512,"policy_id":"reasoning_constraint_stress_thinking_v2","policy_revision":"generation_policy_v1","prompt_directive":null,"prompt_transform_id":"reasoning_constraint_stress_terminal_v1","protocol_version":"generation_protocol_v2","seed":0,"stop_semantics_version":"natural_or_budget_v1","temperature":0.0,"terminal_answer_format":"integer","terminal_answer_marker":"FINAL_ANSWER:","terminal_parser_id":"final_answer_integer_v1","thinking_budget_tokens":256,"thinking_mode":"enabled","top_p":1.0}',
                "85cd12579691d7f6a7dbd6db99745c0bd2f076649c4a827ed66c479096786e26",
            ),
        }
        for policy_id, (canonical_json, fingerprint) in expected.items():
            policy = resolve_generation_policy(policy_id)
            self.assertEqual(policy.canonical_json(), canonical_json)
            self.assertEqual(policy.fingerprint_sha256, fingerprint)


if __name__ == "__main__":
    unittest.main()
