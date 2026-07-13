import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade import __version__
from infergrade.capabilities import (
    _host_mount_path,
    _run_capability_container,
    capability_images_for_request,
    execute_capability_suite,
    resolve_capability_suite,
    summarize_capability_execution,
)
from infergrade.models import CapabilityExecution, RunRequest


class _FakeAdapter(object):
    def generate_text(self, request, prompt, max_tokens):
        return {"text": "generated:%s:%s" % (prompt[:12], max_tokens), "status": "completed", "error": None}


class _MemoryPassingAdapter(object):
    def generate_text(self, request, prompt, max_tokens):
        if "HARBOR-17" in prompt:
            return {"text": "HARBOR-17 uses q4_k_m.", "status": "completed", "error": None}
        if "READY" in prompt:
            return {"text": "READY local runner", "status": "completed", "error": None}
        if "Apple M2 Max" in prompt:
            return {"text": "Apple M2 Max", "status": "completed", "error": None}
        if "fast first tokens" in prompt:
            return {"text": "You prefer fast first tokens and a public model.", "status": "completed", "error": None}
        if "IGRP-8421" in prompt:
            return {"text": "IGRP-8421", "status": "completed", "error": None}
        return {"text": "", "status": "completed", "error": None}


class _MeasuredMemoryAdapter(_MemoryPassingAdapter):
    def generate_text(self, request, prompt, max_tokens):
        result = super().generate_text(request, prompt, max_tokens)
        result.update(
            {
                "latency_ms": 2000.0,
                "time_to_first_token_ms": 100.0,
                "tokens_per_second": 40.0,
                "input_tokens": 20,
                "output_tokens": 12,
                "measurement_source": "fixture_backend_timings",
            }
        )
        return result


class _CodingStaticPassingAdapter(object):
    def generate_text(self, request, prompt, max_tokens):
        if "clamp_score" in prompt:
            return {
                "text": (
                    "```python\n"
                    "def clamp_score(value):\n"
                    "    if value < 0:\n"
                    "        return 0\n"
                    "    if value > 1:\n"
                    "        return 1\n"
                    "    return value\n"
                    "```"
                ),
                "status": "completed",
                "error": None,
            }
        if "parse_model_pair" in prompt:
            return {
                "text": (
                    "```python\n"
                    "def parse_model_pair(text):\n"
                    "    model, quant = text.split('@', 1)\n"
                    "    return {'model': model.strip(), 'quant': quant.strip()}\n"
                    "```"
                ),
                "status": "completed",
                "error": None,
            }
        if "render_status_line" in prompt:
            return {
                "text": (
                    "```python\n"
                    "def render_status_line(status):\n"
                    "    return f\"status={status['state']} model={status['model']}\"\n"
                    "```"
                ),
                "status": "completed",
                "error": None,
            }
        return {"text": "```python\npass\n```", "status": "completed", "error": None}


class _ReasoningPassingAdapter(object):
    def generate_text(self, request, prompt, max_tokens):
        if "Can a dax be red" in prompt:
            return {"text": "no", "status": "completed", "error": None}
        if "How many blue tokens" in prompt:
            return {"text": "7", "status": "completed", "error": None}
        if "A) less than" in prompt:
            return {"text": "B", "status": "completed", "error": None}
        return {"text": "", "status": "completed", "error": None}


class _ReasoningFormattedAnswerAdapter(object):
    def generate_text(self, request, prompt, max_tokens):
        if "Can a dax be red" in prompt:
            return {"text": "Answer: no.", "status": "completed", "error": None}
        if "How many blue tokens" in prompt:
            return {"text": "The answer is 7.", "status": "completed", "error": None}
        if "A) less than" in prompt:
            return {"text": "B) greater than", "status": "completed", "error": None}
        return {"text": "", "status": "completed", "error": None}


class _ReasoningAmbiguousAnswerAdapter(object):
    def generate_text(self, request, prompt, max_tokens):
        if "Can a dax be red" in prompt:
            return {"text": "No, not yes.", "status": "completed", "error": None}
        if "How many blue tokens" in prompt:
            return {"text": "Either 6 or 7.", "status": "completed", "error": None}
        if "A) less than" in prompt:
            return {"text": "A or B", "status": "completed", "error": None}
        return {"text": "", "status": "completed", "error": None}


class _MmluProAdapter(object):
    def generate_text(self, request, prompt, max_tokens):
        if "2 + 2" in prompt:
            return {"text": "D", "status": "completed", "error": None}
        return {"text": "A", "status": "completed", "error": None}


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-capability-")

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_resolve_capability_suite_includes_benchmark_ids(self):
        suite = resolve_capability_suite("agentic_coding", "gold")
        self.assertEqual(suite["suite_id"], "coding_gold_v2")
        self.assertEqual(suite["benchmark_ids"], ["evalplus_humaneval", "evalplus_mbpp"])

    def test_resolve_capability_suite_expands_standard_coding_lane(self):
        suite = resolve_capability_suite("agentic_coding", "standard")
        self.assertEqual(suite["suite_id"], "coding_standard_v3")
        self.assertEqual(suite["benchmark_ids"], ["evalplus_humaneval", "evalplus_mbpp"])

    def test_capability_images_follow_selected_suite(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="gold",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            simulate=False,
        )
        images = capability_images_for_request(request)
        self.assertEqual([item["benchmark_id"] for item in images], ["evalplus_humaneval", "evalplus_mbpp"])

    def test_capability_images_skip_native_multiturn_benchmark(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )
        self.assertEqual(capability_images_for_request(request), [])

    def test_capability_images_skip_native_coding_static_benchmark(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["coding_static_repair_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )
        self.assertEqual(capability_images_for_request(request), [])

    def test_capability_images_skip_native_reasoning_benchmark(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["reasoning_exact_answer_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )
        self.assertEqual(capability_images_for_request(request), [])

    def test_capability_images_include_mmlu_pro_reference_when_selected(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="gold",
            benchmark_check_ids=["mmlu_pro_reference_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )
        images = capability_images_for_request(request)
        self.assertEqual([item["benchmark_id"] for item in images], ["mmlu_pro_reference_v1"])
        self.assertEqual(images[0]["image"], "ghcr.io/bfogels/infergrade-mmlu-pro:%s" % __version__)

    def test_execute_native_multiturn_benchmark_scores_constraints_without_docker(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._run_capability_container") as container_mock:
            execution = execute_capability_suite(_MemoryPassingAdapter(), request)
        container_mock.assert_not_called()
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.score, None)
        self.assertEqual(execution.score_details["observed_weighted_score"], 1.0)
        self.assertEqual(execution.score_details["coverage"]["coverage_fraction"], 0.25)
        self.assertEqual(execution.confidence, None)
        self.assertEqual(execution.component_scores["multiturn_chat_memory_v1"], 1.0)
        result = execution.benchmark_results["multiturn_chat_memory_v1"]
        self.assertEqual(result["primary_metric"]["name"], "constraint_retention_accuracy")
        self.assertEqual(result["metrics"]["passed_constraints"], result["metrics"]["total_constraints"])
        benchmark_dir = os.path.join(self.tempdir, "artifacts", "capability", "multiturn_chat_memory_v1")
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "cases.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "predictions.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "summary.json")))
        capability_run_path = execution.artifacts["multiturn_chat_memory_v1"]["capability_run_path"]
        self.assertTrue(os.path.exists(capability_run_path))
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["artifact_kind"], "capability_run")
        self.assertEqual(artifact["evidence"]["lane"], "decision")
        self.assertEqual(artifact["evidence"]["surface"], "local_assistant_capability")
        self.assertEqual(artifact["summary"]["state"], "scored")
        self.assertEqual(artifact["summary"]["score"], 1.0)
        self.assertEqual({task["state"] for task in artifact["tasks"]}, {"scored"})
        self.assertEqual(artifact["protocol"]["scorer_type"], "exact_match")
        self.assertIn("This is not a global assistant capability score.", artifact["claim_boundary"]["unsupported_claims"])
        capability_summary_path = execution.artifacts["_summary"]["capability_summary_path"]
        self.assertTrue(os.path.exists(capability_summary_path))
        with open(capability_summary_path, "r", encoding="utf-8") as handle:
            capability_summary = json.load(handle)
        self.assertEqual(capability_summary["artifact_kind"], "capability_summary")
        self.assertEqual(
            capability_summary["next_recommended_benchmark_action"]["action"],
            "run_coding_decision_lane",
        )

    def test_native_capability_records_backend_reported_time_and_output_tokens_per_task(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        execution = execute_capability_suite(_MeasuredMemoryAdapter(), request)

        performance = execution.task_performance
        self.assertEqual(performance["attempted_task_count"], 5)
        self.assertEqual(performance["timed_task_count"], 5)
        self.assertEqual(performance["output_token_task_count"], 5)
        self.assertEqual(performance["time_per_task_seconds_median"], 2.0)
        self.assertEqual(performance["output_tokens_per_task_median"], 12.0)
        self.assertEqual(performance["decode_tokens_per_second_median"], 40.0)
        self.assertEqual(performance["total_output_tokens"], 60)
        self.assertEqual(performance["measurement_sources"], ["fixture_backend_timings"])

        capability_run_path = execution.artifacts["multiturn_chat_memory_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["tasks"][0]["latency_ms"], 2000.0)
        self.assertEqual(artifact["tasks"][0]["output_tokens"], 12)
        self.assertEqual(artifact["summary"]["duration_seconds"], 10.0)
        self.assertEqual(artifact["summary"]["output_tokens"], 60)
        self.assertEqual(artifact["summary"]["task_performance"]["time_per_task_seconds_median"], 2.0)

    def test_native_multiturn_preserves_generation_failures_without_docker(self):
        class _FailingMemoryAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                raise RuntimeError("native adapter unavailable")

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            use_case="general_assistant",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
            output_dir=self.tempdir,
            simulate=False,
            generation_preset="deterministic_direct_answer_v1",
        )
        with mock.patch("infergrade.capabilities._run_capability_container") as container_mock:
            execution = execute_capability_suite(_FailingMemoryAdapter(), request)
        container_mock.assert_not_called()
        self.assertEqual(execution.status, "failed")
        result = execution.benchmark_results["multiturn_chat_memory_v1"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["primary_metric"]["value"], None)
        self.assertEqual(result["generation_failure_severity"], "all_failed")
        benchmark_dir = os.path.join(self.tempdir, "artifacts", "capability", "multiturn_chat_memory_v1")
        predictions = []
        with open(os.path.join(benchmark_dir, "predictions.jsonl"), "r", encoding="utf-8") as handle:
            for line in handle:
                predictions.append(json.loads(line))
        self.assertTrue(predictions)
        self.assertEqual({item["generation_status"] for item in predictions}, {"failed"})
        self.assertEqual({item["generation_error"] for item in predictions}, {"native adapter unavailable"})
        self.assertEqual(
            {item["generation_preset_id"] for item in predictions},
            {"deterministic_direct_answer_v1"},
        )
        capability_run_path = execution.artifacts["multiturn_chat_memory_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["summary"]["state"], "failed")
        self.assertEqual(artifact["summary"]["score"], None)
        self.assertEqual({task["state"] for task in artifact["tasks"]}, {"failed"})
        self.assertEqual({task["error_class"] for task in artifact["tasks"]}, {"generation_failed"})
        self.assertIn("attempted the pinned multi-turn assistant", artifact["claim_boundary"]["supported_claims"][0])
        self.assertNotIn("completed the pinned multi-turn assistant", " ".join(artifact["claim_boundary"]["supported_claims"]))
        summary = summarize_capability_execution(request, execution, completed_at="2026-04-29T12:00:00Z")
        self.assertEqual(summary["capability_state"], "failed")
        self.assertIn("generation_failures_exhausted", summary["capability_reason_codes"])

    def test_native_multiturn_partial_generation_failures_emit_partial_artifact(self):
        class _PartiallyFailingMemoryAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                if "HARBOR-17" in prompt:
                    raise RuntimeError("one native generation failed")
                return _MemoryPassingAdapter().generate_text(request, prompt, max_tokens)

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        execution = execute_capability_suite(_PartiallyFailingMemoryAdapter(), request)

        self.assertEqual(execution.status, "partial")
        result = execution.benchmark_results["multiturn_chat_memory_v1"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["generation_failure_severity"], "partial")
        capability_run_path = execution.artifacts["multiturn_chat_memory_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["summary"]["state"], "partial")
        self.assertIsNotNone(artifact["summary"]["score"])
        self.assertEqual({task["state"] for task in artifact["tasks"]}, {"scored", "failed"})
        self.assertIn("partial generation failures", artifact["claim_boundary"]["supported_claims"][0])
        self.assertNotIn("completed the pinned multi-turn assistant", " ".join(artifact["claim_boundary"]["supported_claims"]))

    def test_execute_native_coding_static_benchmark_scores_constraints_without_docker(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["coding_static_repair_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        with mock.patch("infergrade.capabilities._run_capability_container") as container_mock:
            execution = execute_capability_suite(_CodingStaticPassingAdapter(), request)

        container_mock.assert_not_called()
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.score, None)
        self.assertEqual(execution.score_details["observed_weighted_score"], 1.0)
        self.assertEqual(execution.score_details["coverage"]["coverage_fraction"], 0.15)
        self.assertEqual(execution.component_scores["coding_static_repair_v1"], 1.0)
        result = execution.benchmark_results["coding_static_repair_v1"]
        self.assertEqual(result["primary_metric"]["name"], "static_constraint_accuracy")
        self.assertEqual(result["metrics"]["passed_constraints"], result["metrics"]["total_constraints"])
        benchmark_dir = os.path.join(self.tempdir, "artifacts", "capability", "coding_static_repair_v1")
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "cases.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "predictions.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "summary.json")))
        capability_run_path = execution.artifacts["coding_static_repair_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["artifact_kind"], "capability_run")
        self.assertEqual(artifact["evidence"]["lane"], "decision")
        self.assertEqual(artifact["evidence"]["surface"], "local_coding_capability")
        self.assertEqual(artifact["evidence"]["grade"], "thin_local_sample")
        self.assertEqual(artifact["evidence"]["confidence_label"], "thin_local_sample")
        self.assertTrue(artifact["evidence"]["experimental"])
        self.assertEqual(artifact["summary"]["state"], "scored")
        self.assertEqual(artifact["summary"]["score"], 1.0)
        self.assertEqual({task["state"] for task in artifact["tasks"]}, {"scored"})
        self.assertEqual(artifact["protocol"]["scorer_type"], "static_check")
        self.assertEqual(artifact["protocol"]["scoring_policy"], "deterministic_static_code_constraints_v1")
        self.assertIn("This is not a SWE-bench or LiveCodeBench result.", artifact["claim_boundary"]["unsupported_claims"])

    def test_native_coding_static_benchmark_preserves_malformed_and_generation_failures(self):
        class _MixedFailureCodingAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                if "clamp_score" in prompt:
                    return {"text": "I would clamp it with a conditional.", "status": "completed", "error": None}
                if "parse_model_pair" in prompt:
                    raise RuntimeError("native coding generation failed")
                return _CodingStaticPassingAdapter().generate_text(request, prompt, max_tokens)

        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="agentic_coding",
            benchmark_check_ids=["coding_static_repair_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        with mock.patch("infergrade.capabilities._run_capability_container") as container_mock:
            execution = execute_capability_suite(_MixedFailureCodingAdapter(), request)

        container_mock.assert_not_called()
        self.assertEqual(execution.status, "partial")
        result = execution.benchmark_results["coding_static_repair_v1"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["generation_failure_severity"], "partial")
        self.assertEqual(result["metrics"]["malformed_output_count"], 1)
        capability_run_path = execution.artifacts["coding_static_repair_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["summary"]["state"], "partial")
        self.assertEqual(
            {task["error_class"] for task in artifact["tasks"] if task["state"] == "failed"},
            {"malformed_output", "generation_failed"},
        )
        self.assertEqual({task["state"] for task in artifact["tasks"]}, {"scored", "failed"})
        self.assertIn("partial generation or malformed-output failures", artifact["claim_boundary"]["supported_claims"][0])
        self.assertNotIn("completed the pinned coding", " ".join(artifact["claim_boundary"]["supported_claims"]))

    def test_native_coding_static_scores_only_closed_python_fence(self):
        class _ProseOnlyCodingAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                if "clamp_score" in prompt:
                    return {
                        "text": (
                            "Use def clamp_score(value): if value < 0 return 0 if value > 1 return 1 return value.\n"
                            "```python\n"
                            "pass\n"
                            "```"
                        ),
                        "status": "completed",
                        "error": None,
                    }
                return _CodingStaticPassingAdapter().generate_text(request, prompt, max_tokens)

        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["coding_static_repair_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        execution = execute_capability_suite(_ProseOnlyCodingAdapter(), request)

        self.assertEqual(execution.status, "partial")
        case_results = execution.benchmark_results["coding_static_repair_v1"]["case_results"]
        clamp_result = next(item for item in case_results if item["case_id"] == "coding-static-clamp-score")
        self.assertEqual(clamp_result["state"], "failed")
        self.assertEqual(clamp_result["error_class"], "malformed_output")

    def test_native_coding_static_rejects_unclosed_python_fence(self):
        class _UnclosedFenceCodingAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                if "clamp_score" in prompt:
                    return {
                        "text": (
                            "```python\n"
                            "def clamp_score(value):\n"
                            "    if value < 0:\n"
                            "        return 0\n"
                            "    if value > 1:\n"
                            "        return 1\n"
                            "    return value\n"
                        ),
                        "status": "completed",
                        "error": None,
                    }
                return _CodingStaticPassingAdapter().generate_text(request, prompt, max_tokens)

        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["coding_static_repair_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        execution = execute_capability_suite(_UnclosedFenceCodingAdapter(), request)

        self.assertEqual(execution.status, "partial")
        case_results = execution.benchmark_results["coding_static_repair_v1"]["case_results"]
        clamp_result = next(item for item in case_results if item["case_id"] == "coding-static-clamp-score")
        self.assertEqual(clamp_result["state"], "failed")
        self.assertEqual(clamp_result["error_class"], "malformed_output")

    def test_native_coding_static_rejects_multiple_python_fences(self):
        class _MultipleFenceCodingAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                if "clamp_score" in prompt:
                    return {
                        "text": (
                            "```python\n"
                            "pass\n"
                            "```\n"
                            "```python\n"
                            "def clamp_score(value):\n"
                            "    if value < 0:\n"
                            "        return 0\n"
                            "    if value > 1:\n"
                            "        return 1\n"
                            "    return value\n"
                            "```"
                        ),
                        "status": "completed",
                        "error": None,
                    }
                return _CodingStaticPassingAdapter().generate_text(request, prompt, max_tokens)

        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["coding_static_repair_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        execution = execute_capability_suite(_MultipleFenceCodingAdapter(), request)

        self.assertEqual(execution.status, "partial")
        case_results = execution.benchmark_results["coding_static_repair_v1"]["case_results"]
        clamp_result = next(item for item in case_results if item["case_id"] == "coding-static-clamp-score")
        self.assertEqual(clamp_result["state"], "failed")
        self.assertEqual(clamp_result["error_class"], "malformed_output")

    def test_execute_native_reasoning_exact_answer_scores_without_docker(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["reasoning_exact_answer_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        with mock.patch("infergrade.capabilities._run_capability_container") as container_mock:
            execution = execute_capability_suite(_ReasoningPassingAdapter(), request)

        container_mock.assert_not_called()
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.score, None)
        self.assertEqual(execution.score_details["observed_weighted_score"], 1.0)
        self.assertEqual(execution.score_details["coverage"]["coverage_fraction"], 0.2)
        result = execution.benchmark_results["reasoning_exact_answer_v1"]
        self.assertEqual(result["primary_metric"]["name"], "exact_answer_accuracy")
        self.assertEqual(result["metrics"]["correct_count"], result["metrics"]["total_count"])
        capability_run_path = execution.artifacts["reasoning_exact_answer_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["evidence"]["lane"], "decision")
        self.assertEqual(artifact["evidence"]["surface"], "local_reasoning_capability")
        self.assertEqual(artifact["evidence"]["grade"], "thin_local_sample")
        self.assertEqual(artifact["evidence"]["confidence_label"], "thin_local_sample")
        self.assertTrue(artifact["evidence"]["experimental"])
        self.assertEqual(artifact["summary"]["state"], "scored")
        self.assertEqual(artifact["summary"]["score"], 1.0)
        self.assertEqual({task["state"] for task in artifact["tasks"]}, {"scored"})
        self.assertEqual(artifact["protocol"]["scorer_type"], "exact_match")
        self.assertEqual(artifact["protocol"]["scoring_policy"], "deterministic_exact_answer_v1")
        self.assertIn("This is not a global reasoning or intelligence score.", artifact["claim_boundary"]["unsupported_claims"])

    def test_native_reasoning_exact_answer_preserves_generation_failure_as_partial(self):
        class _PartiallyFailingReasoningAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                if "How many blue tokens" in prompt:
                    raise RuntimeError("native reasoning generation failed")
                return _ReasoningPassingAdapter().generate_text(request, prompt, max_tokens)

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            benchmark_check_ids=["reasoning_exact_answer_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        with mock.patch("infergrade.capabilities._run_capability_container") as container_mock:
            execution = execute_capability_suite(_PartiallyFailingReasoningAdapter(), request)

        container_mock.assert_not_called()
        self.assertEqual(execution.status, "partial")
        result = execution.benchmark_results["reasoning_exact_answer_v1"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["generation_failure_severity"], "partial")
        capability_run_path = execution.artifacts["reasoning_exact_answer_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["summary"]["state"], "partial")
        self.assertEqual({task["state"] for task in artifact["tasks"]}, {"scored", "failed"})
        self.assertEqual({task["error_class"] for task in artifact["tasks"] if task["state"] == "failed"}, {"generation_failed"})
        self.assertIn("partial generation failures", artifact["claim_boundary"]["supported_claims"][0])

    def test_native_reasoning_exact_answer_extracts_common_answer_formats(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["reasoning_exact_answer_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        execution = execute_capability_suite(_ReasoningFormattedAnswerAdapter(), request)

        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.score, None)
        self.assertEqual(execution.score_details["observed_weighted_score"], 1.0)
        result = execution.benchmark_results["reasoning_exact_answer_v1"]
        self.assertEqual(result["metrics"]["correct_count"], result["metrics"]["total_count"])

    def test_native_reasoning_exact_answer_rejects_ambiguous_answers(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["reasoning_exact_answer_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

        execution = execute_capability_suite(_ReasoningAmbiguousAnswerAdapter(), request)

        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.score, None)
        self.assertEqual(execution.score_details["observed_weighted_score"], 0.0)
        result = execution.benchmark_results["reasoning_exact_answer_v1"]
        self.assertEqual(result["metrics"]["correct_count"], 0)

    def test_execute_capability_suite_aggregates_primary_scores(self):
        def fake_prepare(spec, benchmark_dir, tier):
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"case_id": "case-1", "task_id": "Task/1", "prompt": "Write code"}) + "\n")

        def fake_evaluate(spec, benchmark_dir):
            score = 0.8 if spec.benchmark_id == "evalplus_humaneval" else 0.6
            return {
                "benchmark_id": spec.benchmark_id,
                "display_name": spec.display_name,
                "status": "completed",
                "primary_metric": {"name": spec.primary_metric_name, "value": score},
                "metrics": {spec.primary_metric_name: score},
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="gold",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(_FakeAdapter(), request)
        self.assertEqual(execution.status, "completed")
        self.assertAlmostEqual(execution.score, 0.729412)
        self.assertEqual(execution.score_method, "weighted_primary_metric_v2")
        self.assertEqual(execution.score_details["score_version"], "local_coding_score_v2")
        self.assertEqual(execution.score_details["coverage"]["coverage_fraction"], 0.85)
        self.assertEqual(execution.confidence, None)
        self.assertEqual(
            execution.score_details["confidence_basis"]["calibration_status"],
            "not_psychometrically_calibrated",
        )
        self.assertEqual(execution.component_scores["evalplus_humaneval"], 0.8)
        self.assertEqual(execution.component_scores["evalplus_mbpp"], 0.6)
        self.assertIn("evalplus_humaneval", execution.benchmark_results)
        self.assertTrue(os.path.exists(os.path.join(self.tempdir, "artifacts", "capability", "evalplus_humaneval", "predictions.jsonl")))
        self.assertIn("capability_run_path", execution.artifacts["evalplus_humaneval"])
        self.assertIn("capability_run_path", execution.artifacts["evalplus_mbpp"])

    def test_execute_evalplus_humaneval_emits_valid_reference_capability_run_artifact(self):
        def fake_prepare(spec, benchmark_dir, tier):
            cases = [
                {"case_id": "HumanEval/0", "task_id": "HumanEval/0", "prompt": "Write add.", "entry_point": "add"},
                {"case_id": "HumanEval/1", "task_id": "HumanEval/1", "prompt": "Write sub.", "entry_point": "sub"},
            ]
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for case in cases:
                    handle.write(json.dumps(case) + "\n")
            with open(os.path.join(benchmark_dir, "benchmark_metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "benchmark_id": "evalplus_humaneval",
                        "dataset": "humaneval",
                        "case_count": 2,
                        "evalplus_revision": "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e",
                        "sample_policy": "humaneval_first_2_from_evalplus_revision",
                    },
                    handle,
                )

        def fake_evaluate(spec, benchmark_dir):
            with open(os.path.join(benchmark_dir, "predictions.jsonl"), "r", encoding="utf-8") as handle:
                predictions = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(len(predictions), 2)
            return {
                "benchmark_id": "evalplus_humaneval",
                "display_name": "EvalPlus HumanEval+",
                "status": "completed",
                "dataset": "humaneval",
                "case_count": 2,
                "evalplus_revision": "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e",
                "sample_policy": "humaneval_first_2_from_evalplus_revision",
                "scoring_policy": "evalplus_pass_at_1_base_plus_v1",
                "primary_metric": {"name": "pass_at_1_plus", "value": 0.5},
                "metrics": {
                    "pass_at_1_base": 1.0,
                    "pass_at_1_plus": 0.5,
                    "passed_count": 1,
                    "failed_count": 1,
                },
                "case_results": [
                    {
                        "task_id": "HumanEval/0",
                        "base_passed": True,
                        "plus_passed": True,
                        "passed": True,
                        "failure_class": None,
                    },
                    {
                        "task_id": "HumanEval/1",
                        "base_passed": True,
                        "plus_passed": False,
                        "passed": False,
                        "failure_class": "test_failed",
                    },
                ],
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            benchmark_check_ids=["evalplus_humaneval"],
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(_FakeAdapter(), request)

        capability_run_path = execution.artifacts["evalplus_humaneval"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["evidence"]["lane"], "reference")
        self.assertEqual(artifact["evidence"]["surface"], "local_coding_capability")
        self.assertEqual(artifact["evidence"]["confidence_label"], "sampled_reference")
        self.assertEqual(artifact["protocol"]["dataset_revision"], "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e")
        self.assertEqual(artifact["protocol"]["sample_policy"], "humaneval_first_2_from_evalplus_revision")
        self.assertEqual(artifact["protocol"]["scorer_type"], "unit_test")
        self.assertEqual(artifact["summary"]["state"], "scored")
        self.assertEqual(artifact["summary"]["score"], 0.5)
        tasks = {task["task_id"]: task for task in artifact["tasks"]}
        self.assertEqual(tasks["HumanEval/0"]["score"], 1.0)
        self.assertEqual(tasks["HumanEval/1"]["score"], 0.0)
        self.assertEqual(tasks["HumanEval/1"]["error_class"], "test_failed")
        self.assertIn("eval_results.json", artifact["artifacts"]["scoring_outputs"])
        self.assertIn("This is not gold evidence.", artifact["claim_boundary"]["unsupported_claims"])

        summary_path = execution.artifacts["_summary"]["capability_summary_path"]
        with open(summary_path, "r", encoding="utf-8") as handle:
            summary = json.load(handle)
        coding = next(item for item in summary["surfaces"] if item["surface"] == "local_coding_capability")
        self.assertEqual(coding["state"], "scored")
        self.assertEqual(coding["lane"], "reference")
        self.assertEqual(coding["confidence_label"], "sampled_reference")

    def test_execute_evalplus_mbpp_emits_valid_reference_capability_run_artifact(self):
        def fake_prepare(spec, benchmark_dir, tier):
            cases = [
                {"case_id": "Mbpp/1", "task_id": "Mbpp/1", "prompt": "Write helper.", "entry_point": "helper"},
                {"case_id": "Mbpp/2", "task_id": "Mbpp/2", "prompt": "Write sorter.", "entry_point": "sorter"},
            ]
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for case in cases:
                    handle.write(json.dumps(case) + "\n")
            with open(os.path.join(benchmark_dir, "benchmark_metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "benchmark_id": "evalplus_mbpp",
                        "dataset": "mbpp",
                        "case_count": 2,
                        "evalplus_revision": "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e",
                        "sample_policy": "mbpp_first_2_from_evalplus_revision",
                    },
                    handle,
                )

        def fake_evaluate(spec, benchmark_dir):
            with open(os.path.join(benchmark_dir, "predictions.jsonl"), "r", encoding="utf-8") as handle:
                predictions = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(len(predictions), 2)
            return {
                "benchmark_id": "evalplus_mbpp",
                "display_name": "EvalPlus MBPP+",
                "status": "completed",
                "dataset": "mbpp",
                "case_count": 2,
                "evalplus_revision": "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e",
                "sample_policy": "mbpp_first_2_from_evalplus_revision",
                "scoring_policy": "evalplus_pass_at_1_base_plus_v1",
                "primary_metric": {"name": "pass_at_1_plus", "value": 0.5},
                "metrics": {
                    "pass_at_1_base": 0.5,
                    "pass_at_1_plus": 0.5,
                    "passed_count": 1,
                    "failed_count": 1,
                },
                "case_results": [
                    {
                        "task_id": "Mbpp/1",
                        "base_passed": True,
                        "plus_passed": True,
                        "passed": True,
                        "failure_class": None,
                    },
                    {
                        "task_id": "Mbpp/2",
                        "base_passed": False,
                        "plus_passed": False,
                        "passed": False,
                        "failure_class": "test_failed",
                    },
                ],
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            benchmark_check_ids=["evalplus_mbpp"],
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(_FakeAdapter(), request)

        capability_run_path = execution.artifacts["evalplus_mbpp"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["evidence"]["lane"], "reference")
        self.assertEqual(artifact["evidence"]["surface"], "local_coding_capability")
        self.assertEqual(artifact["evidence"]["confidence_label"], "sampled_reference")
        self.assertEqual(artifact["protocol"]["dataset"], "mbpp")
        self.assertEqual(artifact["protocol"]["dataset_revision"], "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e")
        self.assertEqual(artifact["protocol"]["sample_policy"], "mbpp_first_2_from_evalplus_revision")
        self.assertEqual(artifact["summary"]["state"], "scored")
        self.assertEqual(artifact["summary"]["score"], 0.5)
        tasks = {task["task_id"]: task for task in artifact["tasks"]}
        self.assertEqual(tasks["Mbpp/1"]["score"], 1.0)
        self.assertEqual(tasks["Mbpp/2"]["score"], 0.0)
        self.assertEqual(tasks["Mbpp/2"]["error_class"], "test_failed")
        self.assertEqual(tasks["Mbpp/2"]["entry_point"], "sorter")
        self.assertIn("samples.jsonl", artifact["artifacts"]["raw_outputs"])
        self.assertIn("eval_results.json", artifact["artifacts"]["scoring_outputs"])
        self.assertIn("mbpp_override.jsonl", artifact["artifacts"]["supporting_files"])
        self.assertIn("This is not gold evidence.", artifact["claim_boundary"]["unsupported_claims"])

    def test_evalplus_artifact_preserves_generation_malformed_and_status_failure_states(self):
        def fake_prepare(spec, benchmark_dir, tier):
            cases = [
                {"case_id": "HumanEval/0", "task_id": "HumanEval/0", "prompt": "Passing task", "entry_point": "ok"},
                {"case_id": "HumanEval/1", "task_id": "HumanEval/1", "prompt": "Malformed task", "entry_point": "bad"},
                {"case_id": "HumanEval/2", "task_id": "HumanEval/2", "prompt": "Test failure task", "entry_point": "test"},
                {"case_id": "HumanEval/3", "task_id": "HumanEval/3", "prompt": "Timeout task", "entry_point": "timeout"},
                {"case_id": "HumanEval/4", "task_id": "HumanEval/4", "prompt": "Generation task", "entry_point": "gen"},
            ]
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for case in cases:
                    handle.write(json.dumps(case) + "\n")
            with open(os.path.join(benchmark_dir, "benchmark_metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "benchmark_id": "evalplus_humaneval",
                        "dataset": "humaneval",
                        "case_count": 5,
                        "evalplus_revision": "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e",
                        "sample_policy": "humaneval_first_5_from_evalplus_revision",
                    },
                    handle,
                )

        def fake_generate(request, prompt, max_tokens):
            if "Malformed" in prompt:
                return {"text": "", "status": "completed", "error": None}
            if "Generation" in prompt:
                return {"text": "", "status": "failed", "error": "backend stopped"}
            return {"text": "def solution():\n    return 1", "status": "completed", "error": None}

        def fake_evaluate(spec, benchmark_dir):
            return {
                "benchmark_id": "evalplus_humaneval",
                "display_name": "EvalPlus HumanEval+",
                "status": "partial",
                "dataset": "humaneval",
                "case_count": 5,
                "evalplus_revision": "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e",
                "sample_policy": "humaneval_first_5_from_evalplus_revision",
                "scoring_policy": "evalplus_pass_at_1_base_plus_v1",
                "primary_metric": {"name": "pass_at_1_plus", "value": 0.2},
                "metrics": {"pass_at_1_base": 0.2, "pass_at_1_plus": 0.2, "passed_count": 1, "failed_count": 3},
                "case_results": [
                    {"task_id": "HumanEval/0", "base_passed": True, "plus_passed": True, "passed": True},
                    {"task_id": "HumanEval/2", "passed": False, "failure_class": "test_failed"},
                    {"task_id": "HumanEval/3", "passed": False, "failure_class": "timeout"},
                ],
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            benchmark_check_ids=["evalplus_humaneval"],
            simulate=False,
        )
        adapter = mock.Mock()
        adapter.generate_text.side_effect = fake_generate
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(adapter, request)

        capability_run_path = execution.artifacts["evalplus_humaneval"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        tasks = {task["task_id"]: task for task in artifact["tasks"]}
        self.assertEqual(tasks["HumanEval/0"]["state"], "scored")
        self.assertEqual(tasks["HumanEval/1"]["state"], "failed")
        self.assertEqual(tasks["HumanEval/1"]["error_class"], "malformed_output")
        self.assertEqual(tasks["HumanEval/2"]["error_class"], "test_failed")
        self.assertEqual(tasks["HumanEval/3"]["error_class"], "timeout")
        self.assertEqual(tasks["HumanEval/4"]["error_class"], "generation_failed")
        self.assertEqual(artifact["summary"]["state"], "partial")

    def test_execute_mmlu_pro_reference_emits_valid_capability_run_artifact(self):
        def fake_prepare(spec, benchmark_dir, tier):
            cases = [
                {
                    "case_id": "mmlu_pro/1",
                    "task_id": "mmlu_pro/1",
                    "category": "math",
                    "prompt": "What is 2 + 2? Final answer letter:",
                    "answer": "D",
                },
                {
                    "case_id": "mmlu_pro/2",
                    "task_id": "mmlu_pro/2",
                    "category": "other",
                    "prompt": "Which option is first? Final answer letter:",
                    "answer": "B",
                },
            ]
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for case in cases:
                    handle.write(json.dumps(case) + "\n")
            with open(os.path.join(benchmark_dir, "benchmark_metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "benchmark_id": "mmlu_pro_reference_v1",
                        "dataset_revision": "54611cde22c74cca43dd78732198de6abe971398",
                        "sample_policy": "category_round_robin_v1",
                        "category_count": 2,
                    },
                    handle,
                )

        def fake_evaluate(spec, benchmark_dir):
            with open(os.path.join(benchmark_dir, "predictions.jsonl"), "r", encoding="utf-8") as handle:
                predictions = [json.loads(line) for line in handle if line.strip()]
            case_results = [
                {
                    "case_id": "mmlu_pro/1",
                    "task_id": "mmlu_pro/1",
                    "category": "math",
                    "expected": "D",
                    "predicted": "D",
                    "correct": True,
                },
                {
                    "case_id": "mmlu_pro/2",
                    "task_id": "mmlu_pro/2",
                    "category": "other",
                    "expected": "B",
                    "predicted": "A",
                    "correct": False,
                },
            ]
            self.assertEqual(len(predictions), 2)
            return {
                "benchmark_id": "mmlu_pro_reference_v1",
                "display_name": "MMLU-Pro reference",
                "status": "completed",
                "primary_metric": {"name": "accuracy", "value": 0.5},
                "metrics": {"accuracy": 0.5, "correct_count": 1, "total_count": 2, "invalid_count": 0},
                "category_metrics": {
                    "math": {"accuracy": 1.0, "correct_count": 1, "total_count": 1},
                    "other": {"accuracy": 0.0, "correct_count": 0, "total_count": 1},
                },
                "case_results": case_results,
                "scoring_policy": "exact_multiple_choice_letter_accuracy_v1",
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            output_dir=self.tempdir,
            benchmark_check_ids=["mmlu_pro_reference_v1"],
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                with mock.patch(
                    "infergrade.capabilities.container_image_identity",
                    return_value={
                        "container_image": "ghcr.io/bfogels/infergrade-mmlu-pro:%s" % __version__,
                        "container_image_id": "sha256:scorer",
                        "container_repo_digests": ["ghcr.io/bfogels/infergrade-mmlu-pro@sha256:scorer"],
                    },
                ):
                    execution = execute_capability_suite(_MmluProAdapter(), request)

        capability_run_path = execution.artifacts["mmlu_pro_reference_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["evidence"]["lane"], "reference")
        self.assertEqual(artifact["evidence"]["confidence_label"], "sampled_reference")
        self.assertEqual(artifact["evidence"]["surface"], "local_reasoning_capability")
        self.assertEqual(artifact["protocol"]["dataset_revision"], "54611cde22c74cca43dd78732198de6abe971398")
        self.assertEqual(artifact["protocol"]["scorer_type"], "multiple_choice")
        self.assertEqual(artifact["summary"]["state"], "scored")
        self.assertEqual(artifact["summary"]["score"], 0.5)
        self.assertEqual(artifact["summary"]["category_metrics"]["math"]["accuracy"], 1.0)
        self.assertEqual(artifact["subject"]["runtime"]["container_image_id"], "sha256:scorer")
        self.assertEqual(artifact["subject"]["runtime"]["container_repo_digests"], ["ghcr.io/bfogels/infergrade-mmlu-pro@sha256:scorer"])
        self.assertEqual(execution.benchmark_results["mmlu_pro_reference_v1"]["container_runtime"]["container_image_id"], "sha256:scorer")
        self.assertEqual([task["score"] for task in artifact["tasks"]], [1.0, 0.0])
        self.assertIn("This is not public leaderboard evidence.", artifact["claim_boundary"]["unsupported_claims"])

        summary_path = execution.artifacts["_summary"]["capability_summary_path"]
        with open(summary_path, "r", encoding="utf-8") as handle:
            summary = json.load(handle)
        reasoning = next(item for item in summary["surfaces"] if item["surface"] == "local_reasoning_capability")
        self.assertEqual(reasoning["state"], "scored")
        self.assertEqual(reasoning["lane"], "reference")
        self.assertEqual(reasoning["confidence_label"], "sampled_reference")

    def test_mmlu_pro_artifact_distinguishes_wrong_malformed_and_generation_failed_tasks(self):
        def fake_prepare(spec, benchmark_dir, tier):
            cases = [
                {
                    "case_id": "mmlu_pro/1",
                    "task_id": "mmlu_pro/1",
                    "category": "math",
                    "prompt": "Wrong answer case",
                    "answer": "D",
                },
                {
                    "case_id": "mmlu_pro/2",
                    "task_id": "mmlu_pro/2",
                    "category": "other",
                    "prompt": "Malformed answer case",
                    "answer": "B",
                },
                {
                    "case_id": "mmlu_pro/3",
                    "task_id": "mmlu_pro/3",
                    "category": "science",
                    "prompt": "Generation failure case",
                    "answer": "C",
                },
            ]
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for case in cases:
                    handle.write(json.dumps(case) + "\n")
            with open(os.path.join(benchmark_dir, "benchmark_metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "benchmark_id": "mmlu_pro_reference_v1",
                        "dataset_revision": "54611cde22c74cca43dd78732198de6abe971398",
                        "sample_policy": "category_round_robin_v1",
                        "category_count": 3,
                    },
                    handle,
                )

        def fake_generate(request, prompt, max_tokens):
            if "Wrong answer" in prompt:
                return {"text": "A", "status": "completed", "error": None}
            if "Malformed answer" in prompt:
                return {"text": "I am not sure.", "status": "completed", "error": None}
            return {"text": "", "status": "failed", "error": "runtime stopped"}

        def fake_evaluate(spec, benchmark_dir):
            return {
                "benchmark_id": "mmlu_pro_reference_v1",
                "display_name": "MMLU-Pro reference",
                "status": "partial",
                "primary_metric": {"name": "accuracy", "value": 0.0},
                "metrics": {"accuracy": 0.0, "correct_count": 0, "total_count": 2, "invalid_count": 1},
                "category_metrics": {
                    "math": {"accuracy": 0.0, "correct_count": 0, "total_count": 1},
                    "other": {"accuracy": 0.0, "correct_count": 0, "total_count": 1},
                },
                "case_results": [
                    {
                        "case_id": "mmlu_pro/1",
                        "task_id": "mmlu_pro/1",
                        "category": "math",
                        "expected": "D",
                        "predicted": "A",
                        "correct": False,
                    },
                    {
                        "case_id": "mmlu_pro/2",
                        "task_id": "mmlu_pro/2",
                        "category": "other",
                        "expected": "B",
                        "predicted": None,
                        "correct": False,
                    },
                ],
                "scoring_policy": "exact_multiple_choice_letter_accuracy_v1",
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            output_dir=self.tempdir,
            benchmark_check_ids=["mmlu_pro_reference_v1"],
            simulate=False,
        )
        adapter = mock.Mock()
        adapter.generate_text.side_effect = fake_generate
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(adapter, request)

        capability_run_path = execution.artifacts["mmlu_pro_reference_v1"]["capability_run_path"]
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        tasks = {task["task_id"]: task for task in artifact["tasks"]}
        self.assertEqual(tasks["mmlu_pro/1"]["state"], "scored")
        self.assertEqual(tasks["mmlu_pro/1"]["score"], 0.0)
        self.assertIsNone(tasks["mmlu_pro/1"]["error_class"])
        self.assertEqual(tasks["mmlu_pro/2"]["state"], "failed")
        self.assertIsNone(tasks["mmlu_pro/2"]["score"])
        self.assertEqual(tasks["mmlu_pro/2"]["error_class"], "malformed_output")
        self.assertEqual(tasks["mmlu_pro/3"]["state"], "failed")
        self.assertIsNone(tasks["mmlu_pro/3"]["score"])
        self.assertEqual(tasks["mmlu_pro/3"]["error_class"], "generation_failed")
        self.assertEqual(artifact["summary"]["state"], "partial")

    def test_execute_capability_suite_handles_partial_failures(self):
        def fake_prepare(spec, benchmark_dir, tier):
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"case_id": "case-1", "task_id": "Task/1", "prompt": "Write code"}) + "\n")

        def fake_evaluate(spec, benchmark_dir):
            if spec.benchmark_id == "evalplus_mbpp":
                raise RuntimeError("mbpp failed")
            return {
                "benchmark_id": spec.benchmark_id,
                "display_name": spec.display_name,
                "status": "completed",
                "primary_metric": {"name": spec.primary_metric_name, "value": 0.5},
                "metrics": {spec.primary_metric_name: 0.5},
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="gold",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(_FakeAdapter(), request)
        self.assertEqual(execution.status, "partial")
        self.assertIsNone(execution.score)
        self.assertEqual(execution.score_details["observed_weighted_score"], 0.5)
        self.assertIn("insufficient_scored_components", execution.score_details["failed_gates"])
        self.assertEqual(execution.benchmark_results["evalplus_mbpp"]["status"], "failed")

    def test_summarize_capability_execution_reports_state_and_coverage(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            simulate=False,
        )
        execution = CapabilityExecution(
            use_case="agentic_coding",
            suite_id="coding_standard_v3",
            suite_ids=["coding_code_editing", "quant_fidelity"],
            benchmark_tier="standard",
            benchmark_group_ids=["coding_core", "coding_breadth", "deployment_chat", "deployment_long_context", "quant_fidelity"],
            benchmark_check_ids=["evalplus_humaneval", "evalplus_mbpp"],
            components=["EvalPlus HumanEval+", "EvalPlus MBPP+"],
            score=0.72,
            score_method="mean_primary_metric_v1",
            component_scores={"evalplus_humaneval": 0.72},
            confidence=0.6,
            status="partial",
            benchmark_results={
                "evalplus_humaneval": {
                    "benchmark_id": "evalplus_humaneval",
                    "display_name": "EvalPlus HumanEval+",
                    "status": "completed",
                    "primary_metric": {"name": "pass_at_1_plus", "value": 0.72},
                }
            },
        )
        summary = summarize_capability_execution(request, execution, completed_at="2026-04-02T12:00:00Z")
        self.assertEqual(summary["capability_state"], "partial")
        self.assertIn("partial_coverage", summary["capability_reason_codes"])
        self.assertEqual(summary["benchmark_coverage"]["planned_count"], 2)
        self.assertEqual(summary["benchmark_coverage"]["scored_count"], 1)
        self.assertEqual(len(summary["capability_component_reports"]), 2)
        self.assertEqual(summary["capability_suite_ids"], ["coding_code_editing", "quant_fidelity"])
        self.assertIn("evalplus_humaneval", summary["selected_benchmark_check_ids"])

    def test_summarize_capability_execution_keeps_failed_state_distinct_from_missing(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            simulate=False,
        )
        execution = CapabilityExecution(
            use_case="agentic_coding",
            suite_id="coding_standard_v3",
            suite_ids=["coding_code_editing"],
            benchmark_tier="standard",
            benchmark_group_ids=["coding_core", "coding_breadth"],
            benchmark_check_ids=["evalplus_humaneval", "evalplus_mbpp"],
            components=["EvalPlus HumanEval+", "EvalPlus MBPP+"],
            score=None,
            score_method=None,
            component_scores={},
            confidence=None,
            status="failed",
            benchmark_results={
                "evalplus_humaneval": {
                    "benchmark_id": "evalplus_humaneval",
                    "display_name": "EvalPlus HumanEval+",
                    "status": "failed",
                    "message": "container exited non-zero",
                }
            },
        )
        summary = summarize_capability_execution(request, execution, completed_at="2026-04-03T12:00:00Z")
        self.assertEqual(summary["capability_state"], "failed")
        self.assertEqual(summary["capability_status"], "failed")
        self.assertIn("benchmark_execution_failed", summary["capability_reason_codes"])
        self.assertEqual(summary["benchmark_coverage"]["coverage_state"], "missing")
        self.assertEqual(summary["benchmark_coverage"]["planned_count"], 2)
        self.assertEqual(summary["benchmark_coverage"]["scored_count"], 0)
        failed_component = next(
            item for item in summary["capability_component_reports"] if item["benchmark_id"] == "evalplus_humaneval"
        )
        self.assertEqual(failed_component["status"], "failed")
        self.assertEqual(summary["capability_run_count"], 0)

    def test_host_mount_path_maps_listener_runs_dir_to_host_runs_dir(self):
        benchmark_dir = os.path.join("/app/runs", "run_example", "artifacts", "capability", "ifeval")
        with mock.patch.dict(
            "os.environ",
            {
                "INFERGRADE_HOST_RUNS_DIR": "/Users/tester/infergrade-runner/runs",
            },
            clear=False,
        ):
            self.assertEqual(
                _host_mount_path(benchmark_dir),
                "/Users/tester/infergrade-runner/runs/run_example/artifacts/capability/ifeval",
            )

    def test_run_capability_container_uses_host_runs_dir_for_nested_docker_mounts(self):
        benchmark_dir = os.path.join("/app/runs", "run_example", "artifacts", "capability", "evalplus_humaneval")
        with mock.patch.dict(
            "os.environ",
            {
                "INFERGRADE_HOST_RUNS_DIR": "/Users/tester/infergrade-runner/runs",
            },
            clear=False,
        ):
            with mock.patch("infergrade.capabilities.install_image"):
                with mock.patch("infergrade.capabilities.subprocess.run", return_value=mock.Mock(returncode=0, stdout="", stderr="")) as run_mock:
                    _run_capability_container("infergrade-evalplus:local", benchmark_dir, ["prepare", "--output-dir", "/work"])
        command = run_mock.call_args[0][0]
        self.assertIn(
            "/Users/tester/infergrade-runner/runs/run_example/artifacts/capability/evalplus_humaneval:/work",
            command,
        )

    def test_execute_capability_suite_reports_benchmark_progress(self):
        events = []

        def fake_prepare(spec, benchmark_dir, tier):
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for index in range(10):
                    handle.write(
                        json.dumps({"case_id": "case-%d" % index, "task_id": "Task/%d" % index, "prompt": "Write code"}) + "\n"
                    )

        def fake_evaluate(spec, benchmark_dir):
            return {
                "benchmark_id": spec.benchmark_id,
                "display_name": spec.display_name,
                "status": "completed",
                "primary_metric": {"name": spec.primary_metric_name, "value": 0.7},
                "metrics": {spec.primary_metric_name: 0.7},
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="agentic_coding",
            output_dir=self.tempdir,
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execute_capability_suite(_FakeAdapter(), request, progress_callback=events.append)
        event_types = [event["event"] for event in events]
        self.assertIn("benchmark_started", event_types)
        self.assertIn("case_progress", event_types)
        self.assertIn("benchmark_completed", event_types)

    def test_execute_capability_suite_scores_supported_assistant_lane(self):
        def fake_prepare(spec, benchmark_dir, tier):
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"case_id": "case-1", "task_id": "IFEval/1", "prompt": "Follow the instruction"}) + "\n")

        def fake_evaluate(spec, benchmark_dir):
            score = 0.84 if spec.benchmark_id == "ifeval" else 0.9
            return {
                "benchmark_id": spec.benchmark_id,
                "display_name": spec.display_name,
                "status": "completed",
                "primary_metric": {"name": spec.primary_metric_name, "value": score},
                "metrics": {spec.primary_metric_name: score},
            }

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            output_dir=self.tempdir,
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(_FakeAdapter(), request)
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.component_scores["ifeval"], 0.84)
        self.assertEqual(execution.component_scores["multiturn_chat_memory_v1"], 0.9)
        self.assertIn("ifeval", execution.benchmark_results)
        self.assertIn("multiturn_chat_memory_v1", execution.benchmark_results)

    def test_execute_capability_suite_marks_all_generation_failures_as_failed(self):
        class _AlwaysFailingAdapter(object):
            def generate_text(self, request, prompt, max_tokens):
                raise RuntimeError("unknown model architecture: 'gemma4'")

        def fake_prepare(spec, benchmark_dir, tier):
            with open(os.path.join(benchmark_dir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for index in range(3):
                    handle.write(json.dumps({"case_id": "case-%d" % index, "task_id": "IFEval/%d" % index, "prompt": "Follow"}) + "\n")

        def fake_evaluate(spec, benchmark_dir):
            return {
                "benchmark_id": spec.benchmark_id,
                "display_name": spec.display_name,
                "status": "completed",
                "primary_metric": {"name": spec.primary_metric_name, "value": 0.0},
                "metrics": {spec.primary_metric_name: 0.0},
            }

        request = RunRequest(
            model="google/gemma-4-27b-it",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            output_dir=self.tempdir,
            simulate=False,
        )
        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            with mock.patch("infergrade.capabilities._evaluate_benchmark", side_effect=fake_evaluate):
                execution = execute_capability_suite(_AlwaysFailingAdapter(), request)
        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.score, None)
        self.assertEqual(execution.benchmark_results["ifeval"]["status"], "failed")
        self.assertEqual(execution.benchmark_results["ifeval"]["generation_failure_severity"], "all_failed")
        self.assertEqual(execution.benchmark_results["ifeval"]["generation_failure_count"], 3)

    def test_execute_capability_suite_writes_real_failure_summary_artifact(self):
        def fake_prepare(spec, benchmark_dir, tier):
            raise RuntimeError("prepare failed")

        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["ifeval"],
            output_dir=self.tempdir,
            simulate=False,
        )

        with mock.patch("infergrade.capabilities._prepare_benchmark_cases", side_effect=fake_prepare):
            execution = execute_capability_suite(_FakeAdapter(), request)

        summary_path = execution.artifacts["ifeval"]["summary_path"]
        self.assertTrue(os.path.exists(summary_path))
        capability_summary_path = execution.artifacts["_summary"]["capability_summary_path"]
        with open(capability_summary_path, "r", encoding="utf-8") as handle:
            capability_summary = json.load(handle)
        pointers = capability_summary["capability_artifacts"]
        self.assertEqual(pointers[0]["artifact_kind"], "benchmark_summary")
        self.assertEqual(pointers[0]["path"], "artifacts/capability/ifeval/summary.json")
        self.assertTrue(os.path.exists(os.path.join(self.tempdir, pointers[0]["path"])))

    def test_summarize_capability_execution_marks_dominant_generation_failures_as_degraded(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            output_dir=self.tempdir,
            simulate=False,
        )
        execution = CapabilityExecution(
            use_case="general_assistant",
            suite_id="assistant_standard_v2",
            suite_ids=["chat_instruction_following"],
            benchmark_tier="standard",
            benchmark_group_ids=["instruction_following"],
            benchmark_check_ids=["ifeval"],
            components=["IFEval"],
            score=None,
            score_method="mean_primary_metric_v1",
            component_scores={},
            confidence=0.6,
            status="partial",
            benchmark_results={
                "ifeval": {
                    "benchmark_id": "ifeval",
                    "display_name": "IFEval",
                    "status": "degraded",
                    "primary_metric": {"name": "prompt_strict_accuracy", "value": 0.41},
                    "generation_failure_count": 60,
                    "generation_failure_rate": 0.6,
                    "generation_failure_severity": "dominant",
                    "completed_cases": 40,
                    "total_cases": 100,
                }
            },
        )
        summary = summarize_capability_execution(request, execution, completed_at="2026-04-03T12:00:00Z")
        self.assertEqual(summary["capability_state"], "partial")
        self.assertIn("generation_failures_dominant", summary["capability_reason_codes"])
        self.assertEqual(summary["benchmark_coverage"]["scored_count"], 0)
        self.assertEqual(summary["capability_component_reports"][0]["generation_failure_severity"], "dominant")


if __name__ == "__main__":
    unittest.main()
