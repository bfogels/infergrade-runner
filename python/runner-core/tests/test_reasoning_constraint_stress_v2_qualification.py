import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from infergrade.benchmark_catalog import (
    benchmark_evidence_exclusion_reason,
    benchmark_scope_summary_for_selection,
    capability_benchmark_ids_for_request,
    load_capability_catalog,
    normalize_request_selection,
    selection_metadata_for_request,
    validate_benchmark_legitimacy_metadata,
)
from infergrade.capabilities import execute_capability_suite
from infergrade.generation_policies import (
    REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
    resolve_generation_policy,
)
from infergrade.models import RunRequest
from infergrade.reasoning_constraint_stress_v2_qualification import (
    BENCHMARK_ID,
    FAILURE_DENOMINATOR_POLICY_ID,
    qualification_cases_for_tier,
    qualification_tier_metadata,
    score_qualification_predictions,
    validate_locked_content_pack,
    validate_tier_cases,
)


class ReasoningConstraintStressV2QualificationTests(unittest.TestCase):
    def test_native_runner_executes_exact_locked_prefixes_and_receipts_profile(self):
        answers = {
            case["prompt"]: case["expected_answers"][0]
            for case in qualification_cases_for_tier("gold")
        }

        class _QualificationAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                return {
                    "text": "FINAL_ANSWER: %s" % answers[prompt],
                    "status": "completed",
                    "generation_policy_id": request.generation_preset,
                    "generation_policy_enforcement": "requested_unverified",
                }

        for tier, count in (("canary", 5), ("standard", 20), ("gold", 40)):
            with self.subTest(tier=tier), tempfile.TemporaryDirectory() as output_dir:
                request = RunRequest(
                    model="fixture/reasoning-v2",
                    backend="llama.cpp",
                    tier=tier,
                    tier_was_explicit=True,
                    benchmark_check_ids=[BENCHMARK_ID],
                    generation_preset="deterministic_v1",
                    output_dir=output_dir,
                    simulate=False,
                )
                execution = execute_capability_suite(_QualificationAdapter(), request)
                result = execution.benchmark_results[BENCHMARK_ID]
                self.assertEqual(result["metrics"]["expected_case_count"], count)
                self.assertEqual(result["metrics"]["total_count"], count)
                self.assertEqual(result["metrics"]["correct_count"], count)
                artifact_path = execution.artifacts[BENCHMARK_ID]["capability_run_path"]
                self.assertTrue(os.path.exists(artifact_path))
                with open(artifact_path, "r", encoding="utf-8") as handle:
                    artifact = json.load(handle)
                self.assertEqual(artifact["protocol"]["case_count"], count)
                self.assertEqual(
                    artifact["subject"]["generation_policy"]["requested_policy"]["top_k"],
                    20,
                )

    def test_locked_pack_and_exact_prefix_identity(self):
        identity = validate_locked_content_pack()
        self.assertEqual(identity["content_pack_benchmark_id"], "reasoning_constraint_stress_v2_content_v1")
        for tier, count in (("canary", 5), ("standard", 20), ("gold", 40)):
            cases = qualification_cases_for_tier(tier)
            self.assertEqual(len(cases), count)
            metadata = qualification_tier_metadata(tier)
            self.assertEqual(metadata["case_count"], count)
            self.assertEqual(metadata["selection_sha256"], identity["tier_selection_digests"][tier])
            validate_tier_cases(cases, tier)

    def test_selection_identity_mutation_fails_closed(self):
        cases = qualification_cases_for_tier("canary")
        mutated = copy.deepcopy(cases)
        mutated[0]["prompt"] += " mutation"
        with self.assertRaisesRegex(ValueError, "reasoning_v2_selection_identity_mismatch:canary:case_payload"):
            validate_tier_cases(mutated, "canary")

    def test_strict_parser_and_failure_denominator(self):
        cases = qualification_cases_for_tier("canary")
        predictions = [
            {
                "case_id": cases[0]["case_id"],
                "generation_status": "completed",
                "completion": "reasoning\nFINAL_ANSWER: +%s" % cases[0]["expected_answers"][0],
                "generation_policy_id": REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
            },
            {
                "case_id": cases[1]["case_id"],
                "generation_status": "completed",
                "completion": "FINAL_ANSWER: %s\ntrailing" % cases[1]["expected_answers"][0],
                "generation_policy_id": REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
            },
            {
                "case_id": cases[2]["case_id"],
                "generation_status": "completed",
                "completion": "FINAL_ANSWER: %s" % cases[2]["expected_answers"][0],
                "token_budget_exhausted": True,
                "generation_policy_id": REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
            },
            {
                "case_id": cases[3]["case_id"],
                "generation_status": "failed",
                "generation_failure_kind": "runtime",
                "generation_policy_id": REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
            },
        ]
        result = score_qualification_predictions(cases, predictions, "canary")
        self.assertEqual(result["metrics"]["correct_count"], 1)
        self.assertEqual(result["metrics"]["total_count"], 3)
        self.assertEqual(result["metrics"]["generation_failure_count"], 2)
        self.assertEqual(result["metrics"]["parser_code_counts"]["trailing_output"], 1)
        self.assertEqual(result["metrics"]["parser_code_counts"]["not_attempted"], 2)
        self.assertEqual(
            result["metrics"]["failure_denominator_policy"]["policy_id"],
            FAILURE_DENOMINATOR_POLICY_ID,
        )
        self.assertEqual(result["case_results"][2]["score"], 0.0)
        self.assertEqual(result["case_results"][2]["error_class"], "token_budget_exhausted")

    def test_generation_policy_and_prediction_identity_fail_closed(self):
        cases = qualification_cases_for_tier("canary")
        prediction = {
            "case_id": cases[0]["case_id"],
            "generation_status": "completed",
            "completion": "FINAL_ANSWER: %s" % cases[0]["expected_answers"][0],
            "generation_policy_id": "deterministic_v1",
        }
        with self.assertRaisesRegex(ValueError, "reasoning_v2_generation_policy_mismatch"):
            score_qualification_predictions(cases, [prediction], "canary")

        foreign = dict(prediction)
        foreign["generation_policy_id"] = REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID
        foreign["case_id"] = "foreign"
        with self.assertRaisesRegex(ValueError, "reasoning_v2_prediction_identity_mismatch:foreign_identity"):
            score_qualification_predictions(cases, [foreign], "canary")

        verified_without_receipt = dict(prediction)
        verified_without_receipt["generation_policy_id"] = (
            REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID
        )
        verified_without_receipt["generation_policy_enforcement"] = "verified"
        with self.assertRaisesRegex(ValueError, "reasoning_v2_policy_enforcement_receipt_missing"):
            score_qualification_predictions(cases, [verified_without_receipt], "canary")

        fingerprint_mismatch = dict(prediction)
        fingerprint_mismatch["generation_policy_id"] = (
            REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID
        )
        fingerprint_mismatch["generation_policy_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "reasoning_v2_generation_policy_fingerprint_mismatch"):
            score_qualification_predictions(cases, [fingerprint_mismatch], "canary")

    def test_candidate_catalog_is_explicit_qualification_only(self):
        catalog = load_capability_catalog()
        self.assertEqual(validate_benchmark_legitimacy_metadata(catalog), [])
        self.assertEqual(
            benchmark_evidence_exclusion_reason(BENCHMARK_ID, catalog),
            "benchmark_qualification_only:unreviewed",
        )
        request = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="standard",
            tier_was_explicit=True,
            benchmark_check_ids=[BENCHMARK_ID],
            generation_preset="deterministic_v1",
        )
        normalize_request_selection(request)
        self.assertEqual(
            request.generation_preset,
            REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
        )
        self.assertEqual(capability_benchmark_ids_for_request(request), [BENCHMARK_ID])
        scope = benchmark_scope_summary_for_selection([BENCHMARK_ID], catalog)
        self.assertEqual(scope["scope"], "qualification_only")
        self.assertEqual(scope["identity_only_benchmark_check_ids"], [])
        self.assertEqual(scope["qualification_only_benchmark_check_ids"], [BENCHMARK_ID])
        metadata = selection_metadata_for_request(request, catalog)
        self.assertEqual(metadata["score_policies"], [])
        self.assertEqual(metadata["identity_only_benchmark_check_ids"], [])
        self.assertEqual(metadata["qualification_only_benchmark_check_ids"], [BENCHMARK_ID])

    def test_reasoning_request_transform_binds_enabled_thinking_policy(self):
        from infergrade.adapters.llama_cpp import _prepare_llama_server_chat

        request = RunRequest(
            model="fixture",
            backend="llama.cpp",
            tier="canary",
            generation_preset=REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
        )
        with mock.patch(
            "infergrade.adapters.llama_cpp._infer_llama_cpp_architecture",
            return_value="qwen35",
        ):
            messages, transform = _prepare_llama_server_chat(
                request,
                "User:\nReturn the answer.\nAssistant:",
            )
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(
            transform["policy_id"],
            REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
        )
        self.assertEqual(transform["thinking_budget_tokens"], "512")
        self.assertEqual(transform["top_k"], "20")
        self.assertIn("FINAL_ANSWER:", transform["prompt_directive"])
        self.assertEqual(transform["policy_enforcement"], "requested_unverified")
        self.assertEqual(
            transform["policy_fingerprint"],
            resolve_generation_policy(
                REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID
            ).fingerprint_sha256,
        )

    @mock.patch("infergrade.adapters.llama_cpp.urllib_request.urlopen")
    def test_llama_server_payload_binds_policy_budget_and_receipt_state(self, urlopen_mock):
        from infergrade.adapters.llama_cpp import _stream_server_chat_completion

        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.readline.side_effect = [
            b'data: {"choices":[{"delta":{"content":"FINAL_ANSWER: 6"},"finish_reason":"stop"}]}\n',
            b'data: [DONE]\n',
        ]
        urlopen_mock.return_value = response
        completion = _stream_server_chat_completion(
            "http://127.0.0.1:8080",
            [{"role": "user", "content": "Return an integer."}],
            1536,
            REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
        )
        sent = json.loads(urlopen_mock.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(sent["thinking_budget_tokens"], 512)
        self.assertEqual(sent["top_k"], 20)
        self.assertEqual(
            completion["generation_policy_id"],
            REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
        )
        self.assertEqual(completion["generation_policy_enforcement"], "requested_unverified")


if __name__ == "__main__":
    unittest.main()
