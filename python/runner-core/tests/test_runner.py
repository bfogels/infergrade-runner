import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import DeploymentExecution
from infergrade.models import RunRequest
from infergrade.runner import run_infergrade


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-test-")

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_run_creates_multi_profile_bundle_for_agentic_coding(self):
        output_dir = os.path.join(self.tempdir, "bundle")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="agentic_coding",
            output_dir=output_dir,
            simulate=True,
        )
        result = run_infergrade(request)
        self.assertTrue(os.path.exists(os.path.join(output_dir, "manifest.json")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "validation.json")))
        self.assertTrue(os.path.isdir(os.path.join(output_dir, "results")))
        result_files = sorted(os.listdir(os.path.join(output_dir, "results")))
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(result_files, ["interactive_chat_v1.json", "long_context_v1.json"])
        with open(os.path.join(output_dir, "results", "interactive_chat_v1.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertIn("ontology", payload)
        self.assertEqual(payload["ontology"]["checkpoint"]["checkpoint_name"], "Qwen2.5-7B-Instruct")
        self.assertEqual(payload["ontology"]["benchmark_subject"]["subject_kind"], "artifact_runtime_binding")
        self.assertEqual(payload["deployment"]["deployment_profile_id"], "interactive_chat_v1")
        self.assertEqual(payload["capability"]["use_case"], "agentic_coding")
        self.assertEqual(payload["verification"]["verification_level"], "experimental")
        with open(os.path.join(output_dir, "progress.json"), "r", encoding="utf-8") as handle:
            progress = json.load(handle)
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["deployment_profiles"]["interactive_chat_v1"]["status"], "completed")

    def test_real_run_records_artifact_resolution_metadata(self):
        artifact_path = os.path.join(self.tempdir, "model.gguf")
        with open(artifact_path, "wb") as handle:
            handle.write(b"runner-artifact-test")

        class FakeAdapter(object):
            def default_backend_flags(self):
                return []

            def resolve_version(self, simulate=True, request=None):
                return "llama.cpp-test"

            def runtime_metadata(self, request):
                return {"container_image": "infergrade-llama-cpp:test", "container_runtime": "docker"}

            def run_capability(self, request, progress_callback=None):
                from infergrade.models import CapabilityExecution

                return CapabilityExecution(
                    use_case=None,
                    suite_id=None,
                    benchmark_tier=request.tier,
                    components=[],
                    score=None,
                    score_method=None,
                    component_scores={},
                    confidence=None,
                    status="skipped",
                )

            def run_deployment_profile(self, request, profile_id, progress_callback=None):
                return DeploymentExecution(
                    profile_id=profile_id,
                    metrics={
                        "ttft_p50_ms": 100.0,
                        "ttft_p95_ms": 100.0,
                        "latency_p50_ms": 400.0,
                        "latency_p95_ms": 400.0,
                        "decode_tokens_per_second_p50": 50.0,
                        "decode_tokens_per_second_p95": 50.0,
                        "request_throughput_per_minute": 150.0,
                        "peak_vram_mb": 1024.0,
                        "load_time_ms": 250.0,
                        "oom_or_failure_rate": 0.0,
                        "deployment_confidence": 0.9,
                    },
                    status="completed",
                    artifacts={},
                )

        output_dir = os.path.join(self.tempdir, "real-bundle")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=artifact_path,
            output_dir=output_dir,
            simulate=False,
        )
        with mock.patch("infergrade.runner.get_adapter", return_value=FakeAdapter()):
            run_infergrade(request)
        self.assertTrue(os.path.exists(os.path.join(output_dir, "artifacts", "receipts", "artifact_resolution.json")))
        with open(os.path.join(output_dir, "provenance", "model_artifact.json"), "r", encoding="utf-8") as handle:
            provenance = json.load(handle)
        self.assertEqual(provenance["quant_artifact"], artifact_path)
        self.assertIsNotNone(provenance["quant_artifact_sha256"])
        self.assertTrue(provenance["quant_artifact_resolved_path"].endswith("model.gguf"))
        with open(os.path.join(output_dir, "results", "interactive_chat_v1.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertTrue(payload["verification"]["artifact_pinned"])
        self.assertEqual(payload["execution"]["container_image"], "infergrade-llama-cpp:test")

    def test_skipped_capability_still_records_use_case(self):
        output_dir = os.path.join(self.tempdir, "capability-skipped")
        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            use_case="general_assistant",
            capability="none",
            output_dir=output_dir,
            simulate=True,
        )
        run_infergrade(request)
        with open(os.path.join(output_dir, "results", "interactive_chat_v1.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["capability"]["use_case"], "general_assistant")
        self.assertEqual(payload["capability"]["capability_status"], "skipped")
        self.assertEqual(payload["capability"]["capability_run_count"], 0)

    def test_existing_output_dir_requires_resume(self):
        output_dir = os.path.join(self.tempdir, "bundle")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            output_dir=output_dir,
            simulate=True,
        )
        run_infergrade(request)
        with self.assertRaises(ValueError):
            run_infergrade(
                RunRequest(
                    model="Qwen/Qwen2.5-7B-Instruct",
                    backend="llama.cpp",
                    tier="canary",
                    output_dir=output_dir,
                    simulate=True,
                )
            )

    def test_resume_skips_completed_profiles(self):
        class FlakyAdapter(object):
            def __init__(self):
                self.calls = []

            def default_backend_flags(self):
                return []

            def resolve_version(self, simulate=True, request=None):
                return "llama.cpp-test"

            def runtime_metadata(self, request):
                return {"container_image": "infergrade-llama-cpp:test", "container_runtime": "docker"}

            def run_capability(self, request, progress_callback=None):
                from infergrade.models import CapabilityExecution

                return CapabilityExecution(
                    use_case=request.use_case,
                    suite_id="sim_suite",
                    benchmark_tier=request.tier,
                    components=["component_a"],
                    score=0.75,
                    score_method="simulated",
                    component_scores={"component_a": 0.75},
                    confidence=0.8,
                    status="completed",
                )

            def run_deployment_profile(self, request, profile_id, progress_callback=None):
                self.calls.append(profile_id)
                if profile_id == "long_context_v1" and self.calls.count(profile_id) == 1:
                    raise RuntimeError("simulated interruption")
                return DeploymentExecution(
                    profile_id=profile_id,
                    metrics={
                        "ttft_p50_ms": 120.0,
                        "ttft_p95_ms": 120.0,
                        "latency_p50_ms": 500.0,
                        "latency_p95_ms": 500.0,
                        "decode_tokens_per_second_p50": 40.0,
                        "decode_tokens_per_second_p95": 40.0,
                        "request_throughput_per_minute": 120.0,
                        "peak_vram_mb": 1500.0,
                        "load_time_ms": 200.0,
                        "oom_or_failure_rate": 0.0,
                        "deployment_confidence": 0.9,
                    },
                    status="completed",
                    artifacts={},
                )

        adapter = FlakyAdapter()
        output_dir = os.path.join(self.tempdir, "resume-bundle")
        initial_request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="agentic_coding",
            output_dir=output_dir,
            simulate=True,
        )
        with mock.patch("infergrade.runner.get_adapter", return_value=adapter):
            with self.assertRaises(RuntimeError):
                run_infergrade(initial_request)
            resumed = run_infergrade(
                RunRequest(
                    model="Qwen/Qwen2.5-7B-Instruct",
                    backend="llama.cpp",
                    tier="standard",
                    use_case="agentic_coding",
                    output_dir=output_dir,
                    resume=True,
                    simulate=True,
                )
            )

        self.assertEqual(adapter.calls, ["interactive_chat_v1", "long_context_v1", "long_context_v1"])
        self.assertEqual(resumed["result_count"], 2)
        with open(os.path.join(output_dir, "progress.json"), "r", encoding="utf-8") as handle:
            progress = json.load(handle)
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["deployment_profiles"]["interactive_chat_v1"]["status"], "completed")
        self.assertEqual(progress["deployment_profiles"]["long_context_v1"]["status"], "completed")
        with open(os.path.join(output_dir, "summary.json"), "r", encoding="utf-8") as handle:
            summary = json.load(handle)
        self.assertEqual(summary["result_count"], 2)

    def test_resume_completed_bundle_reuses_existing_summary(self):
        output_dir = os.path.join(self.tempdir, "completed-bundle")
        first = run_infergrade(
            RunRequest(
                model="Qwen/Qwen2.5-7B-Instruct",
                backend="llama.cpp",
                tier="canary",
                output_dir=output_dir,
                simulate=True,
            )
        )
        with mock.patch("infergrade.runner.capture_environment", side_effect=AssertionError("should not recapture")):
            resumed = run_infergrade(
                RunRequest(
                    model="Qwen/Qwen2.5-7B-Instruct",
                    backend="llama.cpp",
                    tier="canary",
                    output_dir=output_dir,
                    resume=True,
                    simulate=True,
                )
            )
        self.assertEqual(first["bundle_id"], resumed["bundle_id"])
        self.assertEqual(first["summary_path"], resumed["summary_path"])


if __name__ == "__main__":
    unittest.main()
