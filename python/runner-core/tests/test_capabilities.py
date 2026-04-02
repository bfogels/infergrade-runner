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
            benchmark_tier="standard",
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


if __name__ == "__main__":
    unittest.main()
