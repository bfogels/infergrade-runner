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
        self.assertTrue(os.path.exists(os.path.join(output_dir, "report.md")))
        self.assertTrue(result["report_path"].endswith("report.md"))
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
        self.assertEqual(payload["capability"]["capability_state"], "scored")
        self.assertEqual(payload["capability"]["benchmark_coverage"]["planned_count"], 3)
        self.assertEqual(payload["capability"]["benchmark_coverage"]["scored_count"], 2)
        self.assertIn("perplexity_reference_v1", payload["capability"]["selected_benchmark_check_ids"])
        self.assertEqual(len(payload["capability"]["capability_component_reports"]), 3)
        self.assertEqual(payload["fidelity"]["fidelity_state"], "not_yet_measured")
        self.assertEqual(payload["verification"]["verification_level"], "experimental")
        with open(os.path.join(output_dir, "report.md"), "r", encoding="utf-8") as handle:
            report = handle.read()
        self.assertIn("# InferGrade Runner Report", report)
        self.assertIn("Qwen2.5-7B-Instruct", report)
        self.assertIn("Deployment Metrics", report)
        self.assertIn("Reference suite", report)
        with open(os.path.join(output_dir, "progress.json"), "r", encoding="utf-8") as handle:
            progress = json.load(handle)
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["deployment_profiles"]["interactive_chat_v1"]["status"], "completed")

    def test_default_output_dir_writes_capability_summary_inside_bundle(self):
        class FakeAdapter(object):
            def default_backend_flags(self):
                return []

            def resolve_version(self, simulate=True, request=None):
                return "llama.cpp-test"

            def runtime_metadata(self, request):
                return {"container_image": None, "container_runtime": None}

            def run_capability(self, request, progress_callback=None):
                from infergrade.capabilities import execute_capability_suite

                return execute_capability_suite(self, request, progress_callback=progress_callback)

            def generate_text(self, request, prompt, max_tokens):
                if "HARBOR-17" in prompt:
                    return {"text": "HARBOR-17 uses q4_k_m.", "status": "completed", "error": None}
                if "READY" in prompt:
                    return {"text": "READY local runner", "status": "completed", "error": None}
                return {"text": "simulated answer", "status": "completed", "error": None}

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

        output_dir = os.path.join("runs", "capability-summary-default-output-test")
        shutil.rmtree(output_dir, ignore_errors=True)
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
            simulate=False,
        )

        result = None
        try:
            with mock.patch("infergrade.runner.get_adapter", return_value=FakeAdapter()):
                with mock.patch("infergrade.runner._bundle_id", return_value="capability-summary-default-output-test"):
                    result = run_infergrade(request)
            output_dir = result["output_dir"]
            with open(os.path.join(output_dir, "manifest.json"), "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["files"]["capability_summary"], "artifacts/capability/capability_summary.json")
            self.assertTrue(os.path.exists(os.path.join(output_dir, "artifacts", "capability", "capability_summary.json")))
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

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
                    suite_ids=[],
                    benchmark_tier=request.tier,
                    benchmark_group_ids=[],
                    benchmark_check_ids=[],
                    components=[],
                    score=None,
                    score_method=None,
                    component_scores={},
                    confidence=None,
                    status="skipped",
                )

            def run_fidelity(self, request):
                from infergrade.models import FidelityExecution

                return FidelityExecution(
                    state="measured",
                    reason_codes=["perplexity_measured"],
                    metrics={
                        "perplexity": {
                            "metric_name": "perplexity",
                            "value": 4.21,
                            "stderr": 0.12,
                            "status": "measured",
                            "comparability_key": "llama.cpp:infergrade_preview_text_v1:ctx128:stride0:out0",
                        }
                    },
                    context={"corpus_id": "infergrade_preview_text_v1"},
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
        self.assertEqual(payload["fidelity"]["fidelity_state"], "measured")
        self.assertEqual(payload["fidelity"]["perplexity"]["value"], 4.21)

    def test_selected_quant_fidelity_emits_capability_artifact_and_summary(self):
        artifact_path = os.path.join(self.tempdir, "model-q4_k_m.gguf")
        with open(artifact_path, "wb") as handle:
            handle.write(b"runner-quant-fidelity-test")

        class FakeAdapter(object):
            def default_backend_flags(self):
                return []

            def resolve_version(self, simulate=True, request=None):
                return "llama.cpp-test"

            def runtime_metadata(self, request):
                return {"native_perplexity_binary": "/opt/llama-perplexity", "runtime_source": "test"}

            def run_capability(self, request, progress_callback=None):
                from infergrade.models import CapabilityExecution

                return CapabilityExecution(
                    use_case=None,
                    suite_id=None,
                    suite_ids=[],
                    benchmark_tier=request.tier,
                    benchmark_group_ids=[],
                    benchmark_check_ids=[],
                    components=[],
                    score=None,
                    score_method=None,
                    component_scores={},
                    confidence=None,
                    status="skipped",
                    artifacts={},
                )

            def run_fidelity(self, request):
                from infergrade.models import FidelityExecution

                return FidelityExecution(
                    state="measured",
                    reason_codes=["perplexity_measured"],
                    metrics={
                        "perplexity": {
                            "metric_name": "perplexity",
                            "value": 3.25,
                            "stderr": 0.01,
                            "bits_per_byte": 1.44,
                            "duration_seconds": 12.5,
                            "corpus_token_count": 2048,
                            "corpus_byte_count": 8192,
                            "status": "measured",
                            "comparability_key": "legacy-key-replaced",
                            "protocol_id": "infergrade_perplexity_v1",
                            "corpus_id": "infergrade_quantfidelity_v1",
                            "corpus_revision": "sha256:test",
                            "protocol_parameters": {"ctx_size": 128, "stride": 0},
                        }
                    },
                    context={
                        "corpus_id": "infergrade_quantfidelity_v1",
                        "corpus_revision": "sha256:test",
                        "protocol_id": "infergrade_perplexity_v1",
                        "protocol_parameters": {"ctx_size": 128, "stride": 0},
                    },
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

        output_dir = os.path.join(self.tempdir, "quant-fidelity-bundle")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["perplexity_reference_v1"],
            benchmark_group_ids=["quant_fidelity"],
            capability_suite_ids=["quant_fidelity"],
            quant_artifact=artifact_path,
            output_dir=output_dir,
            simulate=False,
        )

        with mock.patch("infergrade.runner.get_adapter", return_value=FakeAdapter()):
            run_infergrade(request)

        capability_run_path = os.path.join(output_dir, "artifacts", "capability", "perplexity_reference_v1", "capability_run.json")
        self.assertTrue(os.path.exists(capability_run_path))
        with open(capability_run_path, "r", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["evidence"]["surface"], "quant_fidelity")
        self.assertEqual(artifact["evidence"]["lane"], "reference")
        self.assertEqual(artifact["evidence"]["confidence_label"], "sampled_reference")
        self.assertTrue(artifact["evidence"]["experimental"])
        self.assertEqual(artifact["summary"]["score"], 3.25)
        self.assertEqual(artifact["summary"]["metrics"]["bits_per_byte"], 1.44)
        self.assertEqual(artifact["subject"]["model"]["model_family"]["family_name"], "Qwen2.5")
        self.assertTrue(artifact["subject"]["model"]["comparability_key"])
        self.assertNotEqual(artifact["subject"]["model"]["comparability_key"], "legacy-key-replaced")
        self.assertIn("not a global model-quality score", " ".join(artifact["claim_boundary"]["unsupported_claims"]))

        with open(os.path.join(output_dir, "artifacts", "capability", "perplexity_reference_v1", "summary.json"), "r", encoding="utf-8") as handle:
            fidelity_summary = json.load(handle)
        with open(os.path.join(output_dir, "artifacts", "capability", "perplexity_reference_v1", "fidelity_raw.json"), "r", encoding="utf-8") as handle:
            fidelity_raw = json.load(handle)
        self.assertEqual(fidelity_summary["comparability_key"], artifact["subject"]["model"]["comparability_key"])
        self.assertEqual(
            fidelity_raw["metrics"]["perplexity"]["comparability_key"],
            artifact["subject"]["model"]["comparability_key"],
        )

        with open(os.path.join(output_dir, "artifacts", "capability", "capability_summary.json"), "r", encoding="utf-8") as handle:
            summary = json.load(handle)
        by_surface = {item["surface"]: item for item in summary["surfaces"]}
        quant = by_surface["quant_fidelity"]
        self.assertEqual(quant["state"], "scored")
        self.assertEqual(quant["lane"], "reference")
        self.assertEqual(quant["confidence_label"], "sampled_reference")
        self.assertEqual(quant["capability_artifacts"][0]["benchmark_id"], "perplexity_reference_v1")
        with open(os.path.join(output_dir, "results", "interactive_chat_v1.json"), "r", encoding="utf-8") as handle:
            result_record = json.load(handle)
        self.assertIn("perplexity_reference_v1", result_record["capability"]["selected_benchmark_check_ids"])
        self.assertIn("perplexity_reference_v1", result_record["capability"]["benchmark_coverage"]["planned_benchmark_ids"])
        self.assertIn(
            "perplexity_reference_v1",
            [item["benchmark_id"] for item in result_record["capability"]["benchmark_registry"]],
        )

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
        self.assertEqual(payload["capability"]["capability_state"], "skipped")
        self.assertIn("capability_disabled", payload["capability"]["capability_reason_codes"])
        self.assertEqual(payload["capability"]["capability_run_count"], 0)

    def test_failed_capability_still_records_failed_state_in_bundle(self):
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
                    use_case="general_assistant",
                    suite_id="assistant_standard_v2",
                    suite_ids=["chat_instruction_following"],
                    benchmark_tier=request.tier,
                    benchmark_group_ids=["instruction_following"],
                    benchmark_check_ids=["ifeval"],
                    components=["IFEval"],
                    score=None,
                    score_method=None,
                    component_scores={},
                    confidence=None,
                    status="failed",
                    benchmark_results={
                        "ifeval": {
                            "benchmark_id": "ifeval",
                            "display_name": "IFEval",
                            "status": "failed",
                            "message": "container exited non-zero",
                        }
                    },
                )

            def run_fidelity(self, request):
                from infergrade.models import FidelityExecution

                return FidelityExecution(state="skipped", reason_codes=["fidelity_not_requested"], metrics={}, context={})

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

        output_dir = os.path.join(self.tempdir, "capability-failed")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            output_dir=output_dir,
            simulate=False,
        )
        with mock.patch("infergrade.runner.get_adapter", return_value=FakeAdapter()):
            run_infergrade(request)
        with open(os.path.join(output_dir, "results", "interactive_chat_v1.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["capability"]["capability_status"], "failed")
        self.assertEqual(payload["capability"]["capability_state"], "failed")
        self.assertIn("benchmark_execution_failed", payload["capability"]["capability_reason_codes"])
        self.assertEqual(payload["capability"]["benchmark_coverage"]["scored_count"], 0)
        self.assertEqual(payload["capability"]["capability_component_reports"][0]["status"], "failed")
        with open(os.path.join(output_dir, "report.md"), "r", encoding="utf-8") as handle:
            report = handle.read()
        self.assertIn("Capability state: failed", report)

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
                    suite_ids=["coding_code_editing"],
                    benchmark_tier=request.tier,
                    benchmark_group_ids=["coding_core"],
                    benchmark_check_ids=["evalplus_humaneval"],
                    components=["component_a"],
                    score=0.75,
                    score_method="simulated",
                    component_scores={"component_a": 0.75},
                    confidence=0.8,
                    status="completed",
                )

            def run_fidelity(self, request):
                from infergrade.models import FidelityExecution

                return FidelityExecution(
                    state="measured",
                    reason_codes=["perplexity_measured"],
                    metrics={"perplexity": {"value": 5.1, "status": "measured"}},
                    context={"corpus_id": "infergrade_preview_text_v1"},
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
            with open(os.path.join(output_dir, "report.md"), "r", encoding="utf-8") as handle:
                failure_report = handle.read()
            self.assertIn("failed before a complete bundle was finalized", failure_report)
            self.assertIn("simulated interruption", failure_report)
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
