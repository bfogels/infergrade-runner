import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.capabilities import capability_images_for_request, execute_capability_suite, resolve_capability_suite
from infergrade.models import RunRequest


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


if __name__ == "__main__":
    unittest.main()
