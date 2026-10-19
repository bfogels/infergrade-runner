import json
import os
import tempfile
import unittest
from unittest import mock

from infergrade.adapters.llama_cpp import LlamaCppAdapter, _probe_native_compute
from infergrade.models import RunRequest
from infergrade.native_memory import NativeMemoryExhausted, is_memory_failure, recovery_flags, policy_summary, effective_configuration
from infergrade.runtime_placement import record_runtime_placement

MODULE = "infergrade.adapters.llama_cpp."
OOM = "ggml_metal_synchronize: error: command buffer 0 failed\nerror: Insufficient Memory (00000008:kIOGPUCommandBufferCallbackErrorOutOfMemory)"
SUPPORTED = frozenset(("--no-mmap", "--fit-target"))
LOG = "load_tensors: MTL0 model buffer size = 2000 MiB\nload_tensors: offloaded 12/33 layers to GPU\nllama_context: n_ctx = 4096\n"


def request(**kwargs):
    return RunRequest(model="LiquidAI/LFM2.5-24B-A2B", backend="llama.cpp", tier="canary",
                      execution_mode="local_native", simulate=False, **kwargs)


class NativeMemoryPolicyTests(unittest.TestCase):
    def test_oom_requires_specific_evidence(self):
        for text in (OOM, "CUDA error: out of memory", "cudaMalloc failed", "VK_ERROR_OUT_OF_DEVICE_MEMORY"):
            self.assertTrue(is_memory_failure(text), text)
        for text in ("Compute error.", "HTTP Error 500", "server exited", "GPU working set exceeded recommended size", "request timed out", "unknown architecture"):
            self.assertFalse(is_memory_failure(text), text)

    def test_bounded_ladder_preserves_requested_flags_and_context(self):
        req = request()
        original = list(req.backend_flags)
        flags = ["--fit", "on", "--log-verbosity", "4"]
        second = recovery_flags(req, flags, 0, SUPPORTED)
        self.assertEqual(second, flags + ["--no-mmap"])
        third = recovery_flags(req, second, 1, SUPPORTED)
        self.assertEqual(third, second + ["--fit-target", "4096"])
        self.assertIsNone(recovery_flags(req, third, 2, SUPPORTED))
        self.assertEqual(req.backend_flags, original)

    def test_explicit_placement_and_unsupported_flags_are_never_overridden(self):
        for flags in (["--fit", "off"], ["--fit", "on", "--mmap"], ["--n-gpu-layers=12"],
                      ["--device", "CUDA0"], ["--cpu-moe"], ["--fit-target", "2048"], ["-ngl", "99"]):
            self.assertIsNone(recovery_flags(request(backend_flags=flags), flags, 0, SUPPORTED), flags)
        self.assertIsNone(recovery_flags(request(), ["--fit", "on"], 0, frozenset()))
        self.assertIsNone(recovery_flags(request(runtime_selector={"accelerator": {"api": "cpu"}}), ["--fit", "on"], 0, SUPPORTED))

    def test_explicit_no_mmap_can_increase_margin_once(self):
        req = request(backend_flags=["--fit", "on", "--no-mmap"])
        flags = recovery_flags(req, req.backend_flags, 0, SUPPORTED)
        self.assertIn("4096", flags)
        self.assertIsNone(recovery_flags(req, flags, 1, SUPPORTED))

    def test_identity_depends_on_effective_settings_not_prior_profiles(self):
        req = request()
        req._native_memory_step = 1
        req._native_memory_flags = ["--fit", "on", "--no-mmap"]
        before = effective_configuration(req)
        req._native_memory_observations = [{"role": "deployment_server", "context_tokens": 8192,
                                            "effective_memory_flags": ["--fit", "on"], "recovery_step": 0}]
        self.assertEqual(effective_configuration(req), before)
        req._native_memory_flags += ["--fit-target", "4096"]
        self.assertNotEqual(effective_configuration(req), before)



class NativeMemoryServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.req = request(output_dir=self.tmp.name)
        self.adapter = LlamaCppAdapter()
        self.events = []
        self.req._native_memory_progress = self.events.append
        self.children = [mock.Mock(pid=i, poll=mock.Mock(return_value=None)) for i in range(3)]
        for target, value in (("_supports_automatic_fit", True), ("_supported_memory_flags", SUPPORTED),
                              ("_wait_for_native_server_ready", ("http://127.0.0.1:8123", 2.0))):
            patch = mock.patch(MODULE + target, return_value=value); patch.start(); self.addCleanup(patch.stop)
        self.paths = mock.patch.object(self.adapter, "_native_server_path", return_value="/locked/llama-server")
        self.paths.start(); self.addCleanup(self.paths.stop)

    def test_fast_path_keeps_mmap_and_records_unscored_probe(self):
        with mock.patch(MODULE + "subprocess.Popen", return_value=self.children[0]) as popen, \
             mock.patch(MODULE + "_read_log_file", return_value=LOG), \
             mock.patch(MODULE + "_probe_native_compute") as probe:
            session = self.adapter._start_native_server(self.req, "/model.gguf", 8192, "capability_server", "actual prompt")
        self.assertNotIn("--no-mmap", popen.call_args.args[0])
        self.assertIn("8192", popen.call_args.args[0])
        probe.assert_called_once_with("http://127.0.0.1:8123", self.req, "actual prompt")
        self.assertEqual(self.events, [])
        self.assertEqual(session["runtime_placement"]["requested_context_tokens"], 8192)
        self.assertEqual(policy_summary(self.req)["configurations"][0]["recovery_step"], 0)
        os.unlink(session["log_path"])

    def test_health_ok_compute_oom_restarts_before_returning_session(self):
        with mock.patch(MODULE + "subprocess.Popen", side_effect=self.children) as popen, \
             mock.patch(MODULE + "_read_log_file", return_value=LOG), \
             mock.patch(MODULE + "_read_log_after", return_value=OOM), \
             mock.patch(MODULE + "_probe_native_compute", side_effect=[RuntimeError("Compute error."), None]), \
             mock.patch(MODULE + "_stop_process") as stop:
            session = self.adapter._start_native_server(self.req, "/model.gguf", 4096, "preflight")
        self.assertEqual(popen.call_count, 2)
        stop.assert_called_once_with(self.children[0])
        self.assertNotIn("--no-mmap", popen.call_args_list[0].args[0])
        self.assertIn("--no-mmap", popen.call_args_list[1].args[0])
        receipts = os.listdir(os.path.join(self.tmp.name, "artifacts", "runtime-memory"))
        self.assertEqual(len(receipts), 2)
        self.assertTrue(any("Memory fallback" in message for message in self.events))
        self.assertEqual(self.req.backend_flags, [])
        os.unlink(session["log_path"])

    def test_oom_exhaustion_stops_after_three_processes_and_preserves_receipts(self):
        with mock.patch(MODULE + "subprocess.Popen", side_effect=self.children) as popen, \
             mock.patch(MODULE + "_read_log_file", return_value=LOG), \
             mock.patch(MODULE + "_read_log_after", return_value=OOM), \
             mock.patch(MODULE + "_probe_native_compute", side_effect=RuntimeError("Compute error.")), \
             mock.patch(MODULE + "_stop_process") as stop:
            with self.assertRaisesRegex(NativeMemoryExhausted, "Insufficient memory"):
                self.adapter._start_native_server(self.req, "/model.gguf", 4096, "preflight")
        self.assertEqual(popen.call_count, 3)
        self.assertEqual(stop.call_count, 3)
        self.assertEqual(len(os.listdir(os.path.join(self.tmp.name, "artifacts", "runtime-memory"))), 3)
        self.assertIsNone(policy_summary(self.req))

    def test_unrelated_compute_error_is_not_retried(self):
        with mock.patch(MODULE + "subprocess.Popen", return_value=self.children[0]) as popen, \
             mock.patch(MODULE + "_read_log_file", return_value="unsupported graph operation"), \
             mock.patch(MODULE + "_probe_native_compute", side_effect=RuntimeError("Compute error.")), \
             mock.patch(MODULE + "_stop_process"):
            with self.assertRaisesRegex(RuntimeError, "Compute error"):
                self.adapter._start_native_server(self.req, "/model.gguf", 4096, "preflight")
        self.assertEqual(popen.call_count, 1)
        self.assertFalse(hasattr(self.req, "_native_memory_flags"))

    def test_generation_probe_requires_positive_tokens(self):
        with mock.patch(MODULE + "_prepare_llama_server_chat", return_value=(None, None)), \
             mock.patch(MODULE + "_stream_server_completion", return_value={"final_payload": {"tokens_predicted": 0}}):
            with self.assertRaisesRegex(RuntimeError, "no output tokens"):
                _probe_native_compute("http://127.0.0.1:1234", self.req, "hello")

    def test_deployment_restarts_and_excludes_all_prior_measurements(self):
        from test_llama_cpp_adapter import _FAKE_SERVER_COMPLETION, _metrics_from_server_completion
        metrics = _metrics_from_server_completion(_FAKE_SERVER_COMPLETION, {}, 2.0, None)
        ok = {"status": "completed", "metrics": {**metrics, "decode_tokens_per_second": 20.0}}
        old = {"status": "completed", "metrics": {**metrics, "decode_tokens_per_second": 999.0}}
        failed = {"status": "failed", "confirmed_oom": True, "command": ["/locked/llama-server"], "error": "Compute error"}
        self.req.deployment_warmup_runs = 1
        self.req.deployment_measured_runs = 2
        with mock.patch.object(self.adapter, "_ensure_backend_model_compatibility"), \
             mock.patch.object(self.adapter, "_require_local_gguf_artifact", return_value=__file__), \
             mock.patch.object(self.adapter, "_run_container_benchmark", side_effect=[old, old, failed, ok, ok, ok]) as run:
            events = []
            result = self.adapter.run_deployment_profile(self.req, "interactive_chat_v1", events.append)
        self.assertEqual(result.metrics["decode_tokens_per_second_p50"], 20.0)
        self.assertEqual(len(result.artifacts["runs"]), 3)
        self.assertEqual(len(result.artifacts["discarded_memory_attempts"]), 3)
        self.assertEqual([call.kwargs["iteration"] for call in run.call_args_list], [0, 1, 2, 0, 1, 2])
        self.assertTrue(any("previous measurements are excluded" in item.get("message", "") for item in events))

    def test_recovered_controls_follow_native_completion_and_perplexity(self):
        self.req._native_memory_step = 1
        self.req._native_memory_flags = ["--fit", "on", "--no-mmap"]
        with mock.patch.object(self.adapter, "_native_completion_path", return_value="/locked/llama-completion"), \
             mock.patch.object(self.adapter, "_native_perplexity_path", return_value="/locked/llama-perplexity"):
            for tool in ("completion", "perplexity"):
                self.assertEqual(self.adapter._backend_flags(self.req, tool), self.req._native_memory_flags)
            with mock.patch(MODULE + "_supported_memory_flags", return_value=frozenset()):
                with self.assertRaisesRegex(NativeMemoryExhausted, "cannot honor"):
                    self.adapter._backend_flags(self.req, "completion")
            with mock.patch(MODULE + "_supports_automatic_fit", return_value=False):
                with self.assertRaisesRegex(NativeMemoryExhausted, "cannot honor"):
                    self.adapter._backend_flags(self.req, "perplexity")

    def test_cleanup_must_finish_before_a_recovery_process_is_started(self):
        with mock.patch(MODULE + "subprocess.Popen", return_value=self.children[0]) as popen, \
             mock.patch(MODULE + "_read_log_file", return_value=LOG), \
             mock.patch(MODULE + "_read_log_after", return_value=OOM), \
             mock.patch(MODULE + "_probe_native_compute", side_effect=RuntimeError("Compute error")), \
             mock.patch(MODULE + "_stop_process", side_effect=RuntimeError("termination could not be confirmed")):
            with self.assertRaisesRegex(RuntimeError, "termination could not be confirmed"):
                self.adapter._start_native_server(self.req, "/model.gguf", 4096, "preflight")
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(len(os.listdir(os.path.join(self.tmp.name, "artifacts", "runtime-memory"))), 1)

    def test_exhausted_memory_propagates_out_of_capability_scoring(self):
        from infergrade.adapters.base import BaseAdapter
        req = request(use_case="general_assistant")
        with mock.patch("infergrade.adapters.base.execute_capability_suite", side_effect=NativeMemoryExhausted("out of memory")):
            with self.assertRaises(NativeMemoryExhausted):
                BaseAdapter().run_capability(req)

    def test_stale_session_oom_does_not_retry_an_unrelated_later_error(self):
        path = os.path.join(self.tmp.name, "session.log")
        with open(path, "w") as handle:
            handle.write(OOM)
        checkpoint = os.path.getsize(path)
        with open(path, "a") as handle:
            handle.write("\nrequest timed out")
        session = {"log_path": path}
        self.assertFalse(self.adapter._recover_capability_memory(self.req, session, checkpoint))
        self.assertEqual(self.events, [])

    def test_changed_successful_placements_restart_group(self):
        from test_llama_cpp_adapter import _FAKE_SERVER_COMPLETION, _metrics_from_server_completion
        metrics = _metrics_from_server_completion(_FAKE_SERVER_COMPLETION, {}, 2.0, None)
        def sample(fingerprint, speed):
            return {"status": "completed", "metrics": {**metrics, "decode_tokens_per_second": speed},
                    "runtime_placement": {"placement_fingerprint": fingerprint}}
        self.req.deployment_warmup_runs = 0
        self.req.deployment_measured_runs = 2
        with mock.patch.object(self.adapter, "_ensure_backend_model_compatibility"), \
             mock.patch.object(self.adapter, "_require_local_gguf_artifact", return_value=__file__), \
             mock.patch.object(self.adapter, "_run_container_benchmark", side_effect=[sample("a", 99), sample("b", 77), sample("b", 20), sample("b", 20)]):
            result = self.adapter.run_deployment_profile(self.req, "interactive_chat_v1")
        self.assertEqual(result.metrics["decode_tokens_per_second_p50"], 20)
        self.assertEqual(len(result.artifacts["discarded_memory_attempts"]), 2)

    def test_repeated_placement_churn_is_bounded(self):
        from test_llama_cpp_adapter import _FAKE_SERVER_COMPLETION, _metrics_from_server_completion
        metrics = _metrics_from_server_completion(_FAKE_SERVER_COMPLETION, {}, 2.0, None)
        self.req.deployment_warmup_runs = 0
        self.req.deployment_measured_runs = 2
        samples = [{"status": "completed", "metrics": metrics, "runtime_placement": {"placement_fingerprint": str(i)}} for i in range(6)]
        with mock.patch.object(self.adapter, "_ensure_backend_model_compatibility"), \
             mock.patch.object(self.adapter, "_require_local_gguf_artifact", return_value=__file__), \
             mock.patch.object(self.adapter, "_run_container_benchmark", side_effect=samples) as run:
            with self.assertRaisesRegex(RuntimeError, "kept changing"):
                self.adapter.run_deployment_profile(self.req, "interactive_chat_v1")
        self.assertEqual(run.call_count, 6)

    def test_recovery_rejects_silent_context_shrink(self):
        from infergrade.adapters.llama_cpp import _require_recovery_context
        self.req._native_memory_step = 1
        with self.assertRaisesRegex(NativeMemoryExhausted, "preserve the requested context"):
            _require_recovery_context(self.req, ["llama-server", "-c", "8192"], "llama_context: n_ctx = 4096")
        _require_recovery_context(self.req, ["llama-server", "-c", "8192"], "llama_context: n_ctx = 4096\nllama_context: n_ctx = 8192")



if __name__ == "__main__":
    unittest.main()
