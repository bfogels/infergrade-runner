import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

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
        self.assertEqual(execution.score, 1.0)
        self.assertEqual(execution.component_scores["multiturn_chat_memory_v1"], 1.0)
        result = execution.benchmark_results["multiturn_chat_memory_v1"]
        self.assertEqual(result["primary_metric"]["name"], "constraint_retention_accuracy")
        self.assertEqual(result["metrics"]["passed_constraints"], result["metrics"]["total_constraints"])
        benchmark_dir = os.path.join(self.tempdir, "artifacts", "capability", "multiturn_chat_memory_v1")
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "cases.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "predictions.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(benchmark_dir, "summary.json")))

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
        self.assertAlmostEqual(execution.score, 0.7)
        self.assertEqual(execution.component_scores["evalplus_humaneval"], 0.8)
        self.assertEqual(execution.component_scores["evalplus_mbpp"], 0.6)
        self.assertIn("evalplus_humaneval", execution.benchmark_results)
        self.assertTrue(os.path.exists(os.path.join(self.tempdir, "artifacts", "capability", "evalplus_humaneval", "predictions.jsonl")))

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
        self.assertAlmostEqual(execution.score, 0.5)
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
