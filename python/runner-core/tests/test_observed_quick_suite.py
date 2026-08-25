import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.cli import main
from infergrade.observed_quick_suite import (
    OBSERVED_QUICK_PROMPT_DIRECTIVE,
    OBSERVED_QUICK_SUITE_VERSION,
    PROTOCOL_CANARY_PROMPT,
    run_observed_quick_suite,
)
from infergrade.observed_runtime import ObservedRuntimeProbe, parse_local_endpoint
from infergrade.reasoning_constraint_stress_v2_qualification import qualification_cases_for_tier


PRIVATE_ENDPOINT = "http://127.0.0.1:18321"
PRIVATE_MODEL_PATH = "/Users/alice/private/model.gguf"


def _receipt():
    return ObservedRuntimeProbe(
        endpoint=parse_local_endpoint(PRIVATE_ENDPOINT),
        provider="llama_server",
        model_ids=[PRIVATE_MODEL_PATH],
        model_endpoint_status="compatible",
        chat_endpoint_status="compatible",
        generation_profile={
            "max_tokens": 512,
            "stream": False,
            "thinking_control": {"requested": True, "effective": "not_verified"},
        },
    ).to_receipt(selected_model_id=PRIVATE_MODEL_PATH)


class _AnsweringAdapter(object):
    def __init__(self, *, fail_at=None, malformed_canary=False, flexible_outputs=False):
        self.fail_at = fail_at
        self.malformed_canary = malformed_canary
        self.flexible_outputs = flexible_outputs
        self.failure_code = "timeout"
        self.calls = 0
        self.answers = {
            case["prompt"]: case["expected_answers"][0]
            for case in qualification_cases_for_tier("gold")
        }

    def generate_text(self, request, prompt, max_tokens):
        self.calls += 1
        if prompt == PROTOCOL_CANARY_PROMPT:
            text = "answer: 7" if self.malformed_canary else "FINAL_ANSWER: 7"
            return {
                "status": "completed",
                "text": text,
                "error": None,
                "observed_runtime": _receipt(),
            }
        if self.fail_at is not None and self.calls == self.fail_at:
            return {
                "status": "failed",
                "text": "",
                "error": self.failure_code,
                "observed_runtime": _receipt(),
            }
        base_prompt = prompt.rsplit("\n\n" + OBSERVED_QUICK_PROMPT_DIRECTIVE, 1)[0]
        text = (
            "FINAL ANSWER = %s" % self.answers[base_prompt]
            if self.flexible_outputs
            else "work\nFINAL_ANSWER: %s" % self.answers[base_prompt]
        )
        return {
            "status": "completed",
            "text": text,
            "error": None,
            "observed_runtime": _receipt(),
        }


class ObservedQuickSuiteTests(unittest.TestCase):
    def test_exact_tiers_score_without_persisting_endpoint_model_prompt_or_output(self):
        for tier, count in (("canary", 5), ("standard", 20), ("gold", 40)):
            with self.subTest(tier=tier):
                payload = run_observed_quick_suite(_AnsweringAdapter(), tier=tier)
                serialized = json.dumps(payload, sort_keys=True)

                self.assertEqual(payload["contract_version"], OBSERVED_QUICK_SUITE_VERSION)
                self.assertEqual(payload["status"], "completed")
                self.assertEqual(payload["suite"]["selection"]["case_count"], count)
                self.assertEqual(payload["metrics"]["correct_count"], count)
                self.assertEqual(payload["metrics"]["exact_signed_integer_accuracy"], 1.0)
                self.assertEqual(payload["metrics"]["diagnostic_semantic_candidate_count"], count)
                self.assertEqual(payload["metrics"]["diagnostic_semantic_correct_count"], count)
                self.assertFalse(payload["evidence_boundary"]["promotion_eligible"])
                self.assertFalse(payload["evidence_boundary"]["recommendation_eligible"])
                self.assertNotIn(PRIVATE_ENDPOINT, serialized)
                self.assertNotIn(PRIVATE_MODEL_PATH, serialized)
                self.assertNotIn("work\nFINAL_ANSWER", serialized)
                self.assertNotIn("prompt", serialized.lower())

    def test_protocol_canary_failure_aborts_content_without_fake_denominator(self):
        payload = run_observed_quick_suite(
            _AnsweringAdapter(malformed_canary=True),
            tier="standard",
        )

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["protocol_canary"]["parser_code"], "missing_marker")
        self.assertEqual(payload["metrics"]["completed_case_count"], 0)
        self.assertEqual(payload["metrics"]["not_attempted_count"], 20)
        self.assertIsNone(payload["metrics"]["exact_signed_integer_accuracy"])
        self.assertTrue(all(row["state"] == "not_attempted" for row in payload["case_results"]))

    def test_score_inert_diagnostic_separates_format_only_failures(self):
        payload = run_observed_quick_suite(
            _AnsweringAdapter(flexible_outputs=True),
            tier="canary",
        )

        self.assertEqual(payload["metrics"]["correct_count"], 0)
        self.assertEqual(payload["metrics"]["exact_signed_integer_accuracy"], 0.0)
        self.assertEqual(payload["metrics"]["diagnostic_semantic_correct_count"], 5)
        self.assertEqual(payload["metrics"]["diagnostic_failure_class_counts"], {
            "format_only": 5,
            "substantive_wrong": 0,
            "unavailable": 0,
        })
        self.assertTrue(all(row["diagnostic_failure_class"] == "format_only" for row in payload["case_results"]))

    def test_generation_failure_stops_spend_and_preserves_failure_bucket(self):
        adapter = _AnsweringAdapter(fail_at=3)
        payload = run_observed_quick_suite(adapter, tier="canary")

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(adapter.calls, 3)
        self.assertEqual(payload["metrics"]["completed_case_count"], 1)
        self.assertEqual(payload["metrics"]["generation_failure_count"], 1)
        self.assertEqual(payload["metrics"]["not_attempted_count"], 3)
        self.assertEqual(payload["metrics"]["generation_failure_code_counts"], {"timeout": 1})

    def test_generation_failure_redacts_arbitrary_adapter_error(self):
        adapter = _AnsweringAdapter(fail_at=3)
        adapter.failure_code = "/Users/alice/private/token=secret"
        payload = run_observed_quick_suite(adapter, tier="canary")

        serialized = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["metrics"]["generation_failure_code_counts"], {"generation_failed": 1})
        self.assertNotIn("/Users/alice", serialized)
        self.assertNotIn("secret", serialized)

    def test_unexpected_adapter_exception_is_bounded_after_canary(self):
        adapter = _AnsweringAdapter()
        original = adapter.generate_text

        def explode_after_canary(request, prompt, max_tokens):
            if prompt == PROTOCOL_CANARY_PROMPT:
                return original(request, prompt, max_tokens)
            raise RuntimeError("/Users/alice/private/token=secret")

        adapter.generate_text = explode_after_canary
        payload = run_observed_quick_suite(adapter, tier="canary")
        serialized = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["metrics"]["generation_failure_code_counts"], {"generation_failed": 1})
        self.assertNotIn("/Users/alice", serialized)
        self.assertNotIn("secret", serialized)

    def test_unexpected_canary_exception_reaches_cli_as_stable_message(self):
        with mock.patch("infergrade.cli.OpenAICompatibleAdapter") as adapter_mock:
            adapter_mock.return_value.generate_text.side_effect = RuntimeError(
                "/Users/alice/private/token=secret"
            )
            with self.assertRaises(SystemExit) as caught:
                main([
                    "--all",
                    "observe-runtime",
                    "--endpoint",
                    PRIVATE_ENDPOINT,
                    "--provider",
                    "llama_server",
                    "--model-id",
                    PRIVATE_MODEL_PATH,
                ])

        message = str(caught.exception)
        self.assertEqual(
            message,
            "Observed quick suite rejected the request: observed_quick_suite_generation_failed",
        )
        self.assertNotIn("alice", message)
        self.assertNotIn("secret", message)

    def test_all_canonical_runtime_failure_codes_remain_distinct(self):
        for code in ("invalid_json", "invalid_response", "malformed_sse", "empty_response", "provider_error", "request_too_large"):
            adapter = _AnsweringAdapter(fail_at=3)
            adapter.failure_code = code
            payload = run_observed_quick_suite(adapter, tier="canary")
            self.assertEqual(payload["metrics"]["generation_failure_code_counts"], {code: 1})

    def test_invalid_token_budget_fails_before_generation(self):
        adapter = _AnsweringAdapter()
        with self.assertRaisesRegex(ValueError, "observed_quick_suite_invalid_max_tokens"):
            run_observed_quick_suite(adapter, max_tokens=0)
        self.assertEqual(adapter.calls, 0)

    def test_cli_uses_in_memory_model_selection_and_writes_only_redacted_result(self):
        payload = run_observed_quick_suite(_AnsweringAdapter(), tier="canary")
        output = io.StringIO()
        with mock.patch("infergrade.cli.OpenAICompatibleAdapter") as adapter_mock, mock.patch(
            "infergrade.cli.run_observed_quick_suite",
            return_value=payload,
        ) as run_mock, redirect_stdout(output):
            exit_code = main([
                "--all",
                "observe-runtime",
                "--endpoint",
                PRIVATE_ENDPOINT,
                "--provider",
                "llama_server",
                "--model-id",
                PRIVATE_MODEL_PATH,
                "--tier",
                "canary",
            ])

        self.assertEqual(exit_code, 0)
        adapter_mock.assert_called_once_with(
            endpoint=PRIVATE_ENDPOINT,
            provider_hint="llama_server",
            model_id=PRIVATE_MODEL_PATH,
            timeout_seconds=2.0,
            generation_timeout_seconds=300.0,
        )
        run_mock.assert_called_once_with(adapter_mock.return_value, tier="canary", max_tokens=512)
        serialized = output.getvalue()
        self.assertNotIn(PRIVATE_ENDPOINT, serialized)
        self.assertNotIn(PRIVATE_MODEL_PATH, serialized)


if __name__ == "__main__":
    unittest.main()
