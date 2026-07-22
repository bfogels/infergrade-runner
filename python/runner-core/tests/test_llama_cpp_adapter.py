import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade import __version__
from infergrade.adapters.llama_cpp import (
    LlamaCppAdapter,
    _DEFAULT_IMAGE,
    _compute_ttft_ms,
    _decode_utf8_lossy,
    _fetch_container_logs,
    _llama_generation_protocol_error,
    _metrics_from_server_completion,
    _parse_llama_memory_allocations,
    _parse_llama_timings,
    _parse_perplexity_output,
    _prepare_llama_prompt,
    _prepare_llama_server_chat,
    _read_log_file,
    _read_gguf_architecture,
    _safe_tokens_per_second,
    _sample_container_cgroup_memory,
    _sample_process_rss_mb,
    _start_container_memory_monitor,
    _stop_container_memory_monitor,
    _stream_server_completion,
    _stream_server_chat_completion,
    _validate_direct_answer_server_completion,
)
from infergrade.models import RunRequest
from infergrade.profiles import DIRECT_ANSWER_GENERATION_PRESET
from infergrade.runtimes import select_llama_cpp_runtime
from infergrade.capabilities import _coding_static_repair_cases, _reasoning_exact_answer_cases


_FAKE_TIMING_LOG = """
llama_print_timings:        load time =     617.57 ms
llama_print_timings: prompt eval time =     574.22 ms /    16 tokens (35.89 ms per token, 27.87 tokens per second)
llama_print_timings:        eval time =    1285.25 ms /    32 runs   (40.16 ms per token, 24.90 tokens per second)
llama_print_timings:       total time =    1901.48 ms /    48 tokens
"""

_FAKE_SUMMARY_LOG = """
[ Prompt: 65.2 t/s | Generation: 25.1 t/s ]
"""

_FAKE_SERVER_LOG = """
llama_model_load:        CPU_Mapped model buffer size =   108.50 MiB
llama_model_load:      Metal_Mapped model buffer size =  3776.15 MiB
llama_kv_cache_init:      Metal0 KV buffer size =   512.00 MiB
slot print_timing: id  2 | task 2 |
prompt eval time =    2185.99 ms /     8 tokens (  273.25 ms per token,     3.66 tokens per second)
       eval time =     908.05 ms /     6 tokens (  151.34 ms per token,     6.61 tokens per second)
      total time =    3094.04 ms /    14 tokens
"""

_FAKE_SERVER_COMPLETION = {
    "elapsed_ms": 3145.85,
    "first_token_ms": 2242.26,
    "text": "Good day to you.",
    "final_payload": {
        "tokens_predicted": 6,
        "tokens_evaluated": 8,
        "timings": {
            "prompt_n": 8,
            "prompt_ms": 2189.581,
            "prompt_per_second": 3.6536670714625306,
            "predicted_n": 6,
            "predicted_ms": 904.755,
            "predicted_per_second": 6.631629557172937,
        },
    },
}

_FAKE_PERPLEXITY_LOG = """
perplexity: calculating perplexity over 16 chunks, n_ctx=128, batch_size=2048, n_seq=16
perplexity: 28.96 seconds per pass - ETA Final estimate: PPL = 1.6244 +/- 0.07827
llama_perf_context_print:       total time =   28989.04 ms /  2049 tokens
"""


class LlamaCppAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-llama-adapter-")
        self.env_patch = mock.patch.dict(os.environ, {"INFERGRADE_RUNTIME_CACHE_DIR": self.tempdir.name})
        self.env_patch.start()
        self.model_path = os.path.join(self.tempdir.name, "model.gguf")
        with open(self.model_path, "w", encoding="utf-8") as handle:
            handle.write("fake gguf")

    def tearDown(self):
        self.env_patch.stop()
        self.tempdir.cleanup()

    @mock.patch(
        "infergrade.adapters.llama_cpp._start_gpu_monitor",
        return_value={"baseline_vram_mb": None, "samples": [], "stop_event": None, "thread": None},
    )
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen", side_effect=OSError("launch failed"))
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/missing/llama-server")
    def test_native_startup_failure_preserves_original_error(self, _server_path_mock, _popen_mock, _gpu_monitor_mock):
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            llama_cpp_server_path="/missing/llama-server",
            simulate=False,
        )

        result = adapter._run_native_benchmark(
            request=request,
            model_path=self.model_path,
            profile_id="interactive_chat_v1",
            profile_spec={"ctx_size": 2048, "prompt": "hello", "max_tokens": 8},
            is_warmup=False,
            iteration=1,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "launch failed")
        self.assertIsNone(result["peak_memory_mb"])

    def test_parse_llama_timings_extracts_expected_metrics(self):
        parsed = _parse_llama_timings(_FAKE_TIMING_LOG)
        self.assertEqual(parsed["load_time_ms"], 617.57)
        self.assertEqual(parsed["prompt_eval_time_ms"], 574.22)
        self.assertEqual(parsed["eval_tokens_per_second"], 24.9)
        self.assertEqual(_compute_ttft_ms(parsed), 614.38)
        self.assertEqual(_safe_tokens_per_second(parsed), 24.9)

    def test_parse_llama_timings_extracts_summary_throughput(self):
        parsed = _parse_llama_timings(_FAKE_SUMMARY_LOG)
        self.assertEqual(parsed["prompt_tokens_per_second"], 65.2)
        self.assertEqual(parsed["eval_tokens_per_second"], 25.1)

    def test_parse_llama_memory_allocations_keeps_model_and_kv_distinct(self):
        parsed = _parse_llama_memory_allocations(_FAKE_SERVER_LOG)
        self.assertEqual(parsed["model_buffer_bytes"], 4073350758)
        self.assertEqual(parsed["kv_cache_bytes"], 536870912)

    def test_sample_process_rss_reports_current_process_working_set(self):
        self.assertGreater(_sample_process_rss_mb(os.getpid()), 0)

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_sample_container_memory_prefers_kernel_cgroup_peak(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="container_cgroup_v2_peak:1258291200\n")
        value, method = _sample_container_cgroup_memory("infergrade-test")
        self.assertEqual(value, 1200.0)
        self.assertEqual(method, "container_cgroup_v2_peak")
        self.assertEqual(run_mock.call_args[0][0][0:3], ["docker", "exec", "infergrade-test"])

    @mock.patch("infergrade.adapters.llama_cpp._sample_container_cgroup_memory")
    def test_stop_container_memory_monitor_keeps_largest_sample_and_method(self, sample_mock):
        sample_mock.return_value = (900.0, "container_cgroup_v2_peak")
        stop_event = mock.Mock()
        handle = {
            "stop_event": stop_event,
            "thread": None,
            "samples": [
                (850.0, "container_cgroup_current_sampled"),
                (950.0, "container_cgroup_v2_peak"),
            ],
            "container_name": "infergrade-test",
        }
        value, method = _stop_container_memory_monitor(handle)
        self.assertEqual(value, 950.0)
        self.assertEqual(method, "container_cgroup_v2_peak")
        stop_event.set.assert_called_once_with()

    @mock.patch("infergrade.adapters.llama_cpp.threading.Thread")
    @mock.patch("infergrade.adapters.llama_cpp._sample_container_cgroup_memory")
    def test_container_kernel_peak_counter_does_not_start_polling_thread(self, sample_mock, thread_mock):
        sample_mock.return_value = (900.0, "container_cgroup_v2_peak")
        handle = _start_container_memory_monitor("infergrade-test")
        self.assertFalse(handle["polling"])
        self.assertIsNone(handle["thread"])
        thread_mock.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp.threading.Thread")
    @mock.patch("infergrade.adapters.llama_cpp._sample_container_cgroup_memory")
    def test_container_current_counter_starts_bounded_polling_fallback(self, sample_mock, thread_mock):
        sample_mock.return_value = (850.0, "container_cgroup_current_sampled")
        thread = mock.Mock()
        thread_mock.return_value = thread
        handle = _start_container_memory_monitor("infergrade-test")
        self.assertTrue(handle["polling"])
        self.assertIs(handle["thread"], thread)
        thread.start.assert_called_once_with()

    def test_metrics_from_server_completion_extracts_ttft_load_and_prompt_speed(self):
        metrics = _metrics_from_server_completion(
            completion=_FAKE_SERVER_COMPLETION,
            parsed_timings=_parse_llama_timings(_FAKE_SERVER_LOG),
            load_time_ms=1675.42,
            peak_vram_mb=1536.0,
        )
        self.assertEqual(metrics["ttft_ms"], 2242.26)
        self.assertEqual(metrics["latency_ms"], 3145.85)
        self.assertEqual(metrics["prompt_tokens_per_second"], 3.6537)
        self.assertEqual(metrics["decode_tokens_per_second"], 6.6316)
        self.assertEqual(metrics["load_time_ms"], 1675.42)
        self.assertEqual(metrics["peak_vram_mb"], 1536.0)

    def test_parse_perplexity_output_extracts_value_and_context(self):
        parsed = _parse_perplexity_output(_FAKE_PERPLEXITY_LOG)
        self.assertEqual(parsed["perplexity"], 1.6244)
        self.assertEqual(parsed["stderr"], 0.07827)
        self.assertEqual(parsed["corpus_token_count"], 2049)
        self.assertEqual(parsed["duration_seconds"], 28.989)

    def test_decode_utf8_lossy_replaces_invalid_bytes(self):
        self.assertEqual(_decode_utf8_lossy(b"ok\xc4bad"), "ok\ufffdbad")
        self.assertEqual(_decode_utf8_lossy("already text"), "already text")
        self.assertEqual(_decode_utf8_lossy(None), "")

    @mock.patch("infergrade.adapters.llama_cpp._stop_process")
    @mock.patch(
        "infergrade.adapters.llama_cpp._wait_for_native_server_ready",
        return_value=("http://127.0.0.1:8123", 321.0),
    )
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/opt/homebrew/bin/llama-server")
    def test_native_model_preflight_loads_exact_artifact_before_benchmarking(
        self,
        _server_path_mock,
        popen_mock,
        wait_mock,
        stop_mock,
    ):
        process = mock.Mock()
        popen_mock.return_value = process
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            backend="llama.cpp",
            tier="standard",
            execution_mode="local_native",
            quant_artifact=self.model_path,
            simulate=False,
        )

        LlamaCppAdapter().preflight_model(request)

        command = popen_mock.call_args[0][0]
        self.assertEqual(command[0], "/opt/homebrew/bin/llama-server")
        self.assertIn(self.model_path, command)
        self.assertIn("512", command)
        wait_mock.assert_called_once()
        stop_mock.assert_called_once_with(process)

    @mock.patch("infergrade.adapters.llama_cpp._read_log_file")
    @mock.patch("infergrade.adapters.llama_cpp._stop_process")
    @mock.patch(
        "infergrade.adapters.llama_cpp._wait_for_native_server_ready",
        side_effect=RuntimeError("server exited"),
    )
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/opt/homebrew/bin/llama-server")
    def test_native_model_preflight_fails_fast_with_bounded_runtime_tail(
        self,
        _server_path_mock,
        popen_mock,
        _wait_mock,
        stop_mock,
        read_log_mock,
    ):
        process = mock.Mock()
        popen_mock.return_value = process
        read_log_mock.return_value = "\n".join(
            ["old metadata line %d" % index for index in range(50)]
            + ["llama_model_load: unknown model architecture: 'gemma4'"]
        )
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            backend="llama.cpp",
            tier="standard",
            execution_mode="local_native",
            quant_artifact=self.model_path,
            simulate=False,
        )

        with self.assertRaisesRegex(RuntimeError, "failed before capability execution") as raised:
            LlamaCppAdapter().preflight_model(request)

        self.assertIn("unknown model architecture: 'gemma4'", str(raised.exception))
        self.assertNotIn("old metadata line 0", str(raised.exception))
        stop_mock.assert_called_once_with(process)

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    def test_model_preflight_is_noop_outside_native_real_execution(self, popen_mock):
        adapter = LlamaCppAdapter()
        for execution_mode, simulate in (("local_container", False), ("local_native", True)):
            request = RunRequest(
                model="Qwen/Qwen3.5-9B",
                backend="llama.cpp",
                tier="canary",
                execution_mode=execution_mode,
                quant_artifact=self.model_path,
                simulate=simulate,
            )
            adapter.preflight_model(request)
        popen_mock.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_fetch_container_logs_decodes_invalid_bytes(self, run_mock):
        run_mock.return_value = mock.Mock(
            returncode=0,
            stdout=b"line 1\ninvalid: \xc4\n",
            stderr=b"stderr invalid: \xc4\n",
        )
        logs = _fetch_container_logs("container-123")
        self.assertIn("invalid: \ufffd", logs)
        self.assertIn("stderr invalid: \ufffd", logs)
        self.assertNotIn("text", run_mock.call_args.kwargs)

    def test_read_log_file_decodes_invalid_native_log_bytes(self):
        log_path = os.path.join(self.tempdir.name, "native.log")
        with open(log_path, "wb") as handle:
            handle.write(b"native log\ninvalid: \xc4\n")
        self.assertEqual(_read_log_file(log_path), "native log\ninvalid: \ufffd\n")

    def test_reads_gguf_architecture_metadata(self):
        gguf_path = os.path.join(self.tempdir.name, "gemma4.gguf")

        def gguf_string(value):
            encoded = value.encode("utf-8")
            return struct.pack("<Q", len(encoded)) + encoded

        with open(gguf_path, "wb") as handle:
            handle.write(b"GGUF")
            handle.write(struct.pack("<I", 3))
            handle.write(struct.pack("<Q", 0))
            handle.write(struct.pack("<Q", 1))
            handle.write(gguf_string("general.architecture"))
            handle.write(struct.pack("<I", 8))
            handle.write(gguf_string("gemma4"))

        self.assertEqual(_read_gguf_architecture(gguf_path), "gemma4")

    @mock.patch("infergrade.adapters.llama_cpp.docker_available", return_value=True)
    @mock.patch("infergrade.adapters.llama_cpp.install_image")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_uses_container_entrypoint(self, run_mock, _install_image_mock, _docker_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="version: 8508 (9f102a140)\n", stderr="")
        adapter = LlamaCppAdapter()
        version = adapter.resolve_version(simulate=False)
        self.assertEqual(version, "version: 8508 (9f102a140)")
        command = run_mock.call_args[0][0]
        self.assertEqual(command[:5], ["docker", "run", "--rm", "--entrypoint", "llama-cli"])

    @mock.patch("infergrade.adapters.llama_cpp.docker_available", return_value=True)
    @mock.patch("infergrade.adapters.llama_cpp.install_image")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_decodes_invalid_docker_output_bytes(self, run_mock, _install_image_mock, _docker_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout=b"version: \xc4-runtime\n", stderr=b"")
        adapter = LlamaCppAdapter()
        version = adapter.resolve_version(simulate=False)
        self.assertEqual(version, "version: \ufffd-runtime")
        self.assertNotIn("text", run_mock.call_args.kwargs)

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_uses_version_line_from_noisy_native_output(self, run_mock, which_mock):
        which_mock.return_value = "/opt/homebrew/bin/llama-cli"
        run_mock.return_value = mock.Mock(
            returncode=0,
            stdout=(
                "ggml_metal_device_init: tensor API disabled for pre-M5 and pre-A19 devices\n"
                "load_backend: loaded BLAS backend from /opt/homebrew/lib/libggml-blas.so\n"
                "version: 9050 (3980e04d5)\n"
            ),
            stderr="",
        )
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
        )
        version = adapter.resolve_version(simulate=False, request=request)
        self.assertEqual(version, "version: 9050 (3980e04d5)")

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_uses_native_binary_for_local_native(self, run_mock, which_mock):
        which_mock.return_value = "/opt/homebrew/bin/llama-cli"
        run_mock.return_value = mock.Mock(returncode=0, stdout="version: native-test\n", stderr="")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
        )
        version = adapter.resolve_version(simulate=False, request=request)
        self.assertEqual(version, "version: native-test")
        self.assertEqual(run_mock.call_args[0][0], ["/opt/homebrew/bin/llama-cli", "--version"])

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_uses_explicit_native_binary_path(self, run_mock, which_mock):
        which_mock.side_effect = lambda name: name if name == "/custom/llama-cli" else None
        run_mock.return_value = mock.Mock(returncode=0, stdout="version: custom-runtime\n", stderr="")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            llama_cpp_cli_path="/custom/llama-cli",
            simulate=False,
        )
        version = adapter.resolve_version(simulate=False, request=request)
        self.assertEqual(version, "version: custom-runtime")
        self.assertEqual(run_mock.call_args[0][0], ["/custom/llama-cli", "--version"])

    @mock.patch("infergrade.runtimes.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_uses_selected_managed_runtime(self, run_mock, adapter_which_mock, runtime_which_mock):
        runtime_which_mock.side_effect = lambda name: name if name in ("/managed/llama-cli", "/managed/llama-server") else None
        select_llama_cpp_runtime(
            runtime_id="llama-cpp-homebrew-stable-2026-04",
            cli_path="/managed/llama-cli",
            server_path="/managed/llama-server",
        )
        adapter_which_mock.side_effect = lambda name: name if name == "/managed/llama-cli" else None
        run_mock.return_value = mock.Mock(returncode=0, stdout="version: managed-runtime\n", stderr="")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
        )
        version = adapter.resolve_version(simulate=False, request=request)
        self.assertEqual(version, "version: managed-runtime")
        self.assertEqual(run_mock.call_args[0][0], ["/managed/llama-cli", "--version"])

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_rejects_gemma4_on_stable_container(self, run_mock):
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="google/gemma-4-27b-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_container",
            ontology_hints={"architecture": "gemma4", "family_name": "Gemma 4"},
            simulate=False,
        )
        with self.assertRaisesRegex(RuntimeError, "stable container runtime"):
            adapter.resolve_version(simulate=False, request=request)
        run_mock.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_explicit_canonical_image_is_still_stable_not_candidate(self, run_mock):
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            backend_image=_DEFAULT_IMAGE,
            tier="canary",
            execution_mode="local_container",
            ontology_hints={"architecture": "gemma4"},
            simulate=False,
        )
        with self.assertRaisesRegex(RuntimeError, "stable container runtime"):
            LlamaCppAdapter().resolve_version(simulate=False, request=request)
        run_mock.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_rejects_gemma4_detected_from_gguf_metadata(self, run_mock):
        gguf_path = os.path.join(self.tempdir.name, "gemma4.gguf")

        def gguf_string(value):
            encoded = value.encode("utf-8")
            return struct.pack("<Q", len(encoded)) + encoded

        with open(gguf_path, "wb") as handle:
            handle.write(b"GGUF")
            handle.write(struct.pack("<I", 3))
            handle.write(struct.pack("<Q", 0))
            handle.write(struct.pack("<Q", 1))
            handle.write(gguf_string("general.architecture"))
            handle.write(struct.pack("<I", 8))
            handle.write(gguf_string("gemma4"))

        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="google/gemma-4-27b-it",
            quant_artifact=gguf_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_container",
            simulate=False,
        )
        with self.assertRaisesRegex(RuntimeError, "stable container runtime"):
            adapter.resolve_version(simulate=False, request=request)
        run_mock.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_explicit_native_runtime_can_attempt_gemma4_candidate(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="version: 9994 (candidate)\n", stderr="")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            llama_cpp_cli_path="/candidate/llama-cli",
            ontology_hints={"architecture": "gemma4", "family_name": "Gemma 4"},
            simulate=False,
        )
        with mock.patch.object(adapter, "_native_command_path", return_value="/candidate/llama-cli"):
            version = adapter.resolve_version(simulate=False, request=request)
        self.assertEqual(version, "version: 9994 (candidate)")

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_custom_container_can_attempt_gemma4_candidate(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="version: 9994 (candidate)\n", stderr="")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            backend_image="example/llama-cpp-gemma4-candidate:9994",
            tier="canary",
            execution_mode="local_container",
            ontology_hints={"architecture": "gemma4", "family_name": "Gemma 4"},
            simulate=False,
        )
        with mock.patch.object(adapter, "_ensure_docker"), mock.patch(
            "infergrade.adapters.llama_cpp.install_image"
        ):
            version = adapter.resolve_version(simulate=False, request=request)
        self.assertEqual(version, "version: 9994 (candidate)")

    @mock.patch("infergrade.adapters.llama_cpp.install_image")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_generate_text_returns_stdout_payload(self, run_mock, _install_image_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="def solve():\n    return 1\n", stderr=_FAKE_TIMING_LOG)
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            simulate=False,
        )
        generated = adapter.generate_text(request, "Write a function", 128)
        self.assertEqual(generated["status"], "completed")
        self.assertIn("def solve()", generated["text"])
        self.assertEqual(generated["latency_ms"], 1901.48)
        self.assertEqual(generated["time_to_first_token_ms"], 614.38)
        self.assertEqual(generated["tokens_per_second"], 24.9)
        self.assertEqual(generated["input_tokens"], 16)
        self.assertEqual(generated["output_tokens"], 32)
        self.assertEqual(generated["measurement_source"], "llama_cpp_timings")
        command = run_mock.call_args[0][0]
        self.assertEqual(command[:4], ["docker", "run", "--rm", "--entrypoint"])

    @mock.patch("infergrade.adapters.llama_cpp.install_image")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_generate_text_failure_decodes_invalid_external_output(self, run_mock, _install_image_mock):
        run_mock.return_value = mock.Mock(returncode=1, stdout=b"partial \xc4\n", stderr=b"fatal \xc4\n")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            simulate=False,
        )
        with self.assertRaises(RuntimeError) as raised:
            adapter.generate_text(request, "Write a function", 128)
        self.assertIn("partial \ufffd", str(raised.exception))
        self.assertIn("fatal \ufffd", str(raised.exception))
        self.assertNotIn("text", run_mock.call_args.kwargs)

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_generate_text_local_native_uses_host_binary(self, run_mock, which_mock):
        which_mock.side_effect = lambda name: (
            "/opt/homebrew/bin/llama-cli" if name == "llama-cli" else
            "/opt/homebrew/bin/llama-completion" if "llama-completion" in name else None
        )
        run_mock.return_value = mock.Mock(returncode=0, stdout="def solve():\n    return 1\n", stderr=_FAKE_TIMING_LOG)
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
        )
        generated = adapter.generate_text(request, "Write a function", 128)
        self.assertEqual(generated["status"], "completed")
        self.assertEqual(run_mock.call_args[0][0][0], "/opt/homebrew/bin/llama-completion")

    def test_qwen3_direct_answer_preset_adds_versioned_directive(self):
        request = RunRequest(
            model="Qwen/Qwen3-0.6B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        prompt, transform = _prepare_llama_prompt(request, "Answer only A.")
        self.assertEqual(prompt, "Answer only A.\n/no_think")
        self.assertEqual(transform["policy_id"], DIRECT_ANSWER_GENERATION_PRESET)
        self.assertEqual(transform["state"], "appended")

        server_prompt, server_transform = _prepare_llama_prompt(
            request,
            "User: Answer only A.\nAssistant:",
            placement="final_user_turn",
        )
        self.assertEqual(server_prompt, "User: Answer only A.\n/no_think\nAssistant:")
        self.assertEqual(server_transform["state"], "inserted_before_final_assistant_turn")
        self.assertEqual(server_transform["placement"], "final_user_turn")

    def test_qwen3_server_prompt_falls_back_when_turn_marker_is_missing(self):
        request = RunRequest(
            model="Qwen/Qwen3-0.6B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        prompt, transform = _prepare_llama_prompt(
            request,
            "Answer only A.",
            placement="final_user_turn",
        )
        self.assertEqual(prompt, "Answer only A.\n/no_think")
        self.assertEqual(transform["state"], "appended_fallback_no_assistant_turn")

    def test_qwen3_direct_answer_server_uses_structured_chat_and_disables_thinking(self):
        request = RunRequest(
            model="Qwen/Qwen3-4B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        messages, transform = _prepare_llama_server_chat(
            request,
            "Benchmark system instruction.\n\nUser: Give five bullets.\nAssistant:",
        )
        self.assertEqual(
            messages,
            [
                {"role": "system", "content": "Benchmark system instruction."},
                {"role": "user", "content": "Give five bullets."},
            ],
        )
        self.assertEqual(transform["id"], "qwen_chat_template_disable_thinking_v2")
        self.assertEqual(transform["placement"], "structured_messages")

    def test_qwen3_mmlu_chat_records_choice_grammar_constraint(self):
        request = RunRequest(
            model="Qwen/Qwen3-4B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="standard",
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        messages, transform = _prepare_llama_server_chat(
            request,
            "Answer the following multiple-choice question.\n\nQuestion: 2 + 2?\n\nA. 3\nB. 4\n\nFinal answer letter:",
        )

        self.assertEqual(transform["generation_constraint"], "mmlu_choice_a_j_grammar_v1")
        self.assertEqual(messages[0]["role"], "user")

    def test_server_command_requests_runtime_memory_telemetry(self):
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
        )
        command = LlamaCppAdapter()._build_llama_server_command(
            model_path=self.model_path,
            ctx_size=4096,
            request=request,
            host="127.0.0.1",
            port=8123,
        )
        verbosity_index = command.index("--log-verbosity")
        self.assertEqual(command[verbosity_index + 1], "4")

    def test_gemma4_direct_answer_server_uses_structured_chat(self):
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
            ontology_hints={"architecture": "gemma4"},
        )
        messages, transform = _prepare_llama_server_chat(
            request,
            "Benchmark system instruction.\n\nUser: Reply exactly READY.\nAssistant:",
        )
        self.assertEqual(
            messages,
            [
                {"role": "system", "content": "Benchmark system instruction."},
                {"role": "user", "content": "Reply exactly READY."},
            ],
        )
        self.assertEqual(transform["id"], "gemma4_chat_template_disable_thinking_v2")

    @mock.patch.object(LlamaCppAdapter, "_generate_native_server_text")
    def test_gemma4_direct_answer_capability_uses_native_chat_server(self, server_generate_mock):
        server_generate_mock.return_value = {"text": "READY", "status": "completed"}
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
            ontology_hints={"architecture": "gemma4"},
        )
        generated = LlamaCppAdapter().generate_text(request, "Reply exactly READY.", 32)
        self.assertEqual(generated["text"], "READY")
        server_generate_mock.assert_called_once()

    def test_qwen35_direct_answer_server_wraps_plain_reasoning_and_coding_prompts(self):
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        for case in (_reasoning_exact_answer_cases()[0], _coding_static_repair_cases()[0]):
            messages, transform = _prepare_llama_server_chat(request, case["prompt"])
            self.assertEqual(messages, [{"role": "user", "content": case["prompt"].strip()}])
            self.assertEqual(transform["state"], "chat_template_disable_thinking_with_zero_budget_single_user_prompt")

    @mock.patch("infergrade.adapters.llama_cpp.tempfile.NamedTemporaryFile")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", side_effect=RuntimeError("server unavailable"))
    def test_qwen35_server_resolution_failure_does_not_create_temp_log(self, server_path_mock, temp_mock):
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        with self.assertRaisesRegex(RuntimeError, "server unavailable"):
            LlamaCppAdapter()._generate_native_server_text(
                request=request,
                model_path=self.model_path,
                prompt="Plain reasoning prompt",
                max_tokens=32,
            )
        temp_mock.assert_not_called()

    def test_legacy_server_preset_keeps_raw_completion_protocol(self):
        request = RunRequest(
            model="Qwen/Qwen3-4B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset="deterministic_v1",
        )
        self.assertEqual(_prepare_llama_server_chat(request, "User: A\nAssistant:"), (None, None))

    @mock.patch("infergrade.adapters.llama_cpp.urllib_request.urlopen")
    def test_stream_completion_disables_cross_case_prompt_cache(self, urlopen_mock):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.readline.side_effect = [
            b'data: {"content":"A","tokens_predicted":1,"stop":false}\n',
            b'data: {"content":"","tokens_predicted":1,"tokens_evaluated":4,"stop":true,"stop_type":"stop","timings":{"prompt_n":4,"predicted_n":1}}\n',
            b'',
        ]
        urlopen_mock.return_value = response

        completion = _stream_server_completion("http://127.0.0.1:8080", "Answer only A.", 16)

        self.assertEqual(completion["text"], "A")
        sent = json.loads(urlopen_mock.call_args.args[0].data.decode("utf-8"))
        self.assertFalse(sent["cache_prompt"])
        self.assertEqual(sent["prompt"], "Answer only A.")

    @mock.patch("infergrade.adapters.llama_cpp.urllib_request.urlopen")
    def test_stream_chat_completion_collects_content_finish_reason_and_timings(self, urlopen_mock):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.readline.side_effect = [
            b'data: {"choices":[{"delta":{"content":"Direct"},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{"content":" answer"},"finish_reason":"stop"}],"timings":{"predicted_n":2,"predicted_per_second":20}}\n',
            b'data: [DONE]\n',
        ]
        urlopen_mock.return_value = response
        completion = _stream_server_chat_completion(
            "http://127.0.0.1:8080",
            [{"role": "user", "content": "Answer directly"}],
            16,
        )
        self.assertEqual(completion["text"], "Direct answer")
        self.assertEqual(completion["final_payload"]["stop_type"], "stop")
        self.assertEqual(completion["final_payload"]["tokens_predicted"], 2)
        sent = json.loads(urlopen_mock.call_args.args[0].data.decode("utf-8"))
        self.assertFalse(sent["cache_prompt"])
        self.assertEqual(sent["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(sent["thinking_budget_tokens"], 0)
        self.assertNotIn("grammar", sent)

    @mock.patch("infergrade.adapters.llama_cpp.urllib_request.urlopen")
    def test_stream_chat_completion_constrains_mmlu_to_one_answer_letter(self, urlopen_mock):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.readline.side_effect = [
            b'data: {"choices":[{"delta":{"content":"B"},"finish_reason":"stop"}]}\n',
            b'data: [DONE]\n',
        ]
        urlopen_mock.return_value = response

        _stream_server_chat_completion(
            "http://127.0.0.1:8080",
            [{
                "role": "user",
                "content": "Answer the following multiple-choice question.\n\nQuestion: 2 + 2?\n\nA. 3\nB. 4\n\nFinal answer letter:",
            }],
            64,
        )

        sent = json.loads(urlopen_mock.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["grammar"], "root ::= [A-J]")

    def test_direct_answer_deployment_rejects_empty_but_keeps_visible_fixed_budget_output(self):
        transform = {"id": "qwen_chat_template_disable_thinking_v2"}
        with self.assertRaisesRegex(RuntimeError, "without visible answer"):
            _validate_direct_answer_server_completion(
                {"text": "", "final_payload": {"stop_type": "stop"}},
                transform,
            )
        _validate_direct_answer_server_completion(
            {"text": "visible fixed-budget output", "final_payload": {"stop_type": "length"}},
            transform,
        )
        _validate_direct_answer_server_completion(
            {"text": "complete", "final_payload": {"stop_type": "stop"}},
            transform,
        )

    def test_server_metrics_distinguish_natural_stop_from_token_budget_exhaustion(self):
        base = {
            "elapsed_ms": 1000.0,
            "first_token_ms": 100.0,
            "final_payload": {
                "timings": {
                    "prompt_ms": 100.0,
                    "predicted_ms": 900.0,
                    "predicted_n": 40,
                    "prompt_per_second": 100.0,
                    "predicted_per_second": 44.4,
                },
                "stop_type": "length",
            },
        }
        limited = _metrics_from_server_completion(base, {}, 500.0, None)
        self.assertEqual(limited["output_tokens"], 40)
        self.assertTrue(limited["token_budget_exhausted"])
        self.assertFalse(limited["natural_stop"])
        base["final_payload"]["stop_type"] = "stop"
        natural = _metrics_from_server_completion(base, {}, 500.0, None)
        self.assertFalse(natural["token_budget_exhausted"])
        self.assertTrue(natural["natural_stop"])

    def test_default_preset_does_not_change_qwen3_prompt(self):
        request = RunRequest(
            model="Qwen/Qwen3-0.6B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset="deterministic_v1",
        )
        self.assertEqual(_prepare_llama_prompt(request, "Answer only A."), ("Answer only A.", None))

    def test_qwen35_directive_detection_requires_standalone_line(self):
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        mentioned, transform = _prepare_llama_prompt(request, "Explain the literal /no_think string.")
        self.assertTrue(mentioned.endswith("\n/no_think"))
        present, transform = _prepare_llama_prompt(request, "Answer A.\n/no_think")
        self.assertEqual(present, "Answer A.\n/no_think")
        self.assertEqual(transform["state"], "already_present")

    @mock.patch.object(LlamaCppAdapter, "_generate_native_server_text")
    def test_qwen35_direct_answer_capability_uses_native_chat_server(self, server_generate_mock):
        server_generate_mock.return_value = {
            "text": "HARBOR-17 uses q4_k_m.",
            "status": "completed",
        }
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        generated = adapter.generate_text(
            request,
            "User: What saved setup did I pick?\nAssistant:",
            96,
        )
        self.assertEqual(generated["text"], "HARBOR-17 uses q4_k_m.")
        server_generate_mock.assert_called_once_with(
            request=request,
            model_path=self.model_path,
            prompt="User: What saved setup did I pick?\nAssistant:",
            max_tokens=96,
        )

    @mock.patch.object(LlamaCppAdapter, "_generate_native_completion_server_text")
    def test_capability_suite_routes_raw_prompt_generation_through_reused_server(self, server_generate_mock):
        server_generate_mock.return_value = {"text": "A", "status": "completed"}
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        adapter = LlamaCppAdapter()
        adapter._capability_server_reuse_enabled = True

        generated = adapter.generate_text(request, "Answer only A.", 32)

        self.assertEqual(generated["text"], "A")
        server_generate_mock.assert_called_once_with(
            request=request,
            model_path=self.model_path,
            prompt="Answer only A.\n/no_think",
            prompt_transform={
                "id": "qwen_no_think_directive_v1",
                "policy_id": DIRECT_ANSWER_GENERATION_PRESET,
                "state": "appended",
                "placement": "append",
            },
            max_tokens=32,
        )

    @mock.patch.object(LlamaCppAdapter, "_generate_native_server_text")
    def test_qwen36_direct_answer_uses_native_chat_template_parameter(self, server_generate_mock):
        server_generate_mock.return_value = {"text": "A", "status": "completed"}
        request = RunRequest(
            model="Qwen/Qwen3.6-27B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        generated = LlamaCppAdapter().generate_text(request, "Answer only A.", 32)
        self.assertEqual(generated["text"], "A")
        server_generate_mock.assert_called_once()

    def test_gemma4_direct_answer_fails_closed_outside_native_chat_path(self):
        request = RunRequest(
            model="google/gemma-4-E4B-it",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            backend_image="example/llama-cpp-gemma4-candidate:9994",
            tier="canary",
            execution_mode="local_container",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
            ontology_hints={"architecture": "gemma4"},
        )
        with self.assertRaisesRegex(RuntimeError, "requires the local_native llama-server chat path"):
            LlamaCppAdapter().generate_text(request, "Answer only A.", 32)

    def test_qwen36_direct_answer_fails_closed_outside_native_chat_path(self):
        request = RunRequest(
            model="Qwen/Qwen3.6-27B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_container",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
            ontology_hints={"architecture": "qwen35"},
        )
        with self.assertRaisesRegex(RuntimeError, "requires the local_native llama-server chat path"):
            LlamaCppAdapter().generate_text(request, "Answer only A.", 32)

    @mock.patch("infergrade.adapters.llama_cpp._stop_process")
    @mock.patch("infergrade.adapters.llama_cpp._read_log_file", return_value="")
    @mock.patch("infergrade.adapters.llama_cpp._stream_server_chat_completion")
    @mock.patch("infergrade.adapters.llama_cpp._wait_for_native_server_ready", return_value=("http://127.0.0.1:8123", 321.0))
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/opt/homebrew/bin/llama-server")
    def test_qwen35_native_chat_server_preserves_task_timings(
        self,
        native_server_mock,
        popen_mock,
        wait_mock,
        stream_mock,
        read_log_mock,
        stop_mock,
    ):
        stream_mock.return_value = {
            "elapsed_ms": 720.0,
            "first_token_ms": 180.0,
            "text": "HARBOR-17 uses q4_k_m.",
            "final_payload": {
                "stop": True,
                "stop_type": "stop",
                "tokens_predicted": 8,
                "usage": {"prompt_tokens": 42, "completion_tokens": 8},
                "timings": {"predicted_n": 8, "predicted_per_second": 20.0},
            },
        }
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        generated = LlamaCppAdapter()._generate_native_server_text(
            request=request,
            model_path=self.model_path,
            prompt="Replay the saved conversation.\n\nUser: What saved setup did I pick?\nAssistant:",
            max_tokens=96,
        )
        self.assertEqual(generated["status"], "completed")
        self.assertEqual(generated["input_tokens"], 42)
        self.assertEqual(generated["output_tokens"], 8)
        self.assertEqual(generated["tokens_per_second"], 20.0)
        self.assertEqual(generated["time_to_first_token_ms"], 180.0)
        self.assertEqual(generated["measurement_source"], "llama_cpp_server_chat_timings")
        sent_messages = stream_mock.call_args.kwargs["messages"]
        self.assertEqual(sent_messages[-1], {"role": "user", "content": "What saved setup did I pick?"})
        stop_mock.assert_called_once_with(popen_mock.return_value)

    @mock.patch("infergrade.adapters.llama_cpp._stop_process")
    @mock.patch("infergrade.adapters.llama_cpp._stream_server_chat_completion")
    @mock.patch("infergrade.adapters.llama_cpp._wait_for_native_server_ready", return_value=("http://127.0.0.1:8123", 321.0))
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/opt/homebrew/bin/llama-server")
    def test_capability_suite_reuses_one_native_chat_server_across_cases(
        self,
        native_server_mock,
        popen_mock,
        wait_mock,
        stream_mock,
        stop_mock,
    ):
        popen_mock.return_value.poll.return_value = None
        stream_mock.return_value = {
            "elapsed_ms": 720.0,
            "first_token_ms": 180.0,
            "text": "READY",
            "final_payload": {
                "stop_type": "stop",
                "usage": {"prompt_tokens": 12, "completion_tokens": 1},
                "timings": {"prompt_n": 12, "predicted_n": 1, "predicted_per_second": 20.0},
            },
        }
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        adapter = LlamaCppAdapter()
        adapter._capability_server_reuse_enabled = True

        first = adapter._generate_native_server_text(request, self.model_path, "Reply READY.", 32)
        second = adapter._generate_native_server_text(request, self.model_path, "Reply READY again.", 32)
        stream_mock.return_value = {
            "elapsed_ms": 100.0,
            "first_token_ms": None,
            "text": "",
            "final_payload": {"stop_type": "stop", "timings": {}},
        }
        with self.assertRaisesRegex(RuntimeError, "without visible answer"):
            adapter._generate_native_server_text(request, self.model_path, "Fail visibly.", 32)
        self.assertIsNotNone(adapter._capability_server_session)
        adapter._stop_capability_server_session()

        self.assertEqual(first["load_time_ms"], 321.0)
        self.assertIsNone(second["load_time_ms"])
        self.assertEqual(stream_mock.call_count, 3)
        popen_mock.assert_called_once()
        wait_mock.assert_called_once()
        stop_mock.assert_called_once_with(popen_mock.return_value)

    @mock.patch("infergrade.adapters.llama_cpp._stream_server_completion")
    def test_capability_suite_reuses_raw_completion_server_without_prompt_cache_state(self, stream_mock):
        stream_mock.return_value = {
            "elapsed_ms": 400.0,
            "first_token_ms": 100.0,
            "text": "A",
            "final_payload": {
                "stop": True,
                "stop_type": "stop",
                "tokens_evaluated": 8,
                "tokens_predicted": 1,
                "timings": {
                    "prompt_n": 8,
                    "prompt_ms": 100.0,
                    "predicted_n": 1,
                    "predicted_ms": 50.0,
                    "predicted_per_second": 20.0,
                },
            },
        }
        process = mock.MagicMock()
        process.poll.return_value = None
        session = {
            "base_url": "http://127.0.0.1:8123",
            "load_time_ms": 321.0,
            "load_time_reported": False,
            "process": process,
        }
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        adapter = LlamaCppAdapter()
        with mock.patch.object(adapter, "_ensure_capability_server_session", return_value=session):
            first = adapter._generate_native_completion_server_text(
                request,
                self.model_path,
                "Answer only A.\n/no_think",
                {"id": "qwen_no_think_directive_v1"},
                32,
            )
            second = adapter._generate_native_completion_server_text(
                request,
                self.model_path,
                "Answer only A again.\n/no_think",
                {"id": "qwen_no_think_directive_v1"},
                32,
            )

        self.assertEqual(first["load_time_ms"], 321.0)
        self.assertIsNone(second["load_time_ms"])
        self.assertEqual(first["input_tokens"], 8)
        self.assertEqual(first["output_tokens"], 1)
        self.assertEqual(first["measurement_source"], "llama_cpp_server_completion_timings")
        self.assertEqual(
            [call.kwargs["prompt"] for call in stream_mock.call_args_list],
            ["Answer only A.\n/no_think", "Answer only A again.\n/no_think"],
        )

    def test_capability_suite_always_disables_reuse_and_cleans_up(self):
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        adapter = LlamaCppAdapter()
        with mock.patch.object(adapter, "_ensure_backend_model_compatibility"), mock.patch.object(
            adapter,
            "_stop_capability_server_session",
        ) as stop_mock, mock.patch(
            "infergrade.adapters.base.BaseAdapter.run_capability",
            side_effect=RuntimeError("suite failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "suite failed"):
                adapter.run_capability(request)

        self.assertFalse(adapter._capability_server_reuse_enabled)
        stop_mock.assert_called_once_with()

    def test_raw_capability_keeps_one_shot_fallback_when_server_binary_is_missing(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
        )
        adapter = LlamaCppAdapter()
        with mock.patch.object(adapter, "_ensure_backend_model_compatibility"), mock.patch.object(
            adapter,
            "_native_server_path",
            side_effect=RuntimeError("server unavailable"),
        ), mock.patch(
            "infergrade.adapters.base.BaseAdapter.run_capability",
            return_value="legacy-one-shot-result",
        ) as base_run_mock:
            result = adapter.run_capability(request)

        self.assertEqual(result, "legacy-one-shot-result")
        self.assertFalse(adapter._capability_server_reuse_enabled)
        base_run_mock.assert_called_once()

    @mock.patch("infergrade.adapters.llama_cpp._stop_process")
    @mock.patch("infergrade.adapters.llama_cpp._wait_for_native_server_ready", return_value=("http://127.0.0.1:8123", 100.0))
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/opt/homebrew/bin/llama-server")
    def test_capability_server_restarts_only_for_context_growth_or_process_exit(
        self,
        native_server_mock,
        popen_mock,
        wait_mock,
        stop_mock,
    ):
        processes = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        for process in processes:
            process.poll.return_value = None
        popen_mock.side_effect = processes
        request = RunRequest(
            model="Qwen/Qwen3.5-9B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
            generation_preset=DIRECT_ANSWER_GENERATION_PRESET,
        )
        adapter = LlamaCppAdapter()

        first = adapter._ensure_capability_server_session(request, self.model_path, 5000)
        same = adapter._ensure_capability_server_session(request, self.model_path, 7000)
        grown = adapter._ensure_capability_server_session(request, self.model_path, 9000)
        processes[1].poll.return_value = 1
        recovered = adapter._ensure_capability_server_session(request, self.model_path, 12000)
        adapter._stop_capability_server_session()

        self.assertIs(first, same)
        self.assertEqual(first["ctx_size"], 8192)
        self.assertIsNot(first, grown)
        self.assertEqual(grown["ctx_size"], 16384)
        self.assertIsNot(grown, recovered)
        self.assertEqual(popen_mock.call_count, 3)
        self.assertEqual(wait_mock.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in stop_mock.call_args_list],
            processes,
        )

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_generate_text_local_native_requires_noninteractive_completion_binary(self, run_mock, which_mock):
        which_mock.side_effect = lambda name: "/opt/homebrew/bin/llama-cli" if name == "llama-cli" else None
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen3-0.6B",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            execution_mode="local_native",
            simulate=False,
        )
        with self.assertRaisesRegex(RuntimeError, "requires llama-completion beside llama-cli"):
            adapter.generate_text(request, "Answer only A", 64)
        run_mock.assert_not_called()

    def test_generation_protocol_rejects_observed_interactive_llama_cli_output(self):
        observed = (
            "Loading model...\n\navailable commands:\n  /exit stop or exit\n\n"
            "> Question ... (truncated)\n\n[Start thinking]\nunfinished"
        )
        error = _llama_generation_protocol_error(observed, max_tokens=64, output_tokens=None)
        self.assertIn("interactive llama-cli output contaminated", error)

    def test_generation_protocol_rejects_token_exhaustion_inside_thinking(self):
        error = _llama_generation_protocol_error(
            "<think>Still reasoning and no final answer",
            max_tokens=64,
            output_tokens=64,
        )
        self.assertIn("exhausted max_tokens", error)

    def test_generation_protocol_accepts_closed_thinking_with_answer(self):
        self.assertIsNone(
            _llama_generation_protocol_error(
                "<think>brief</think>\nB",
                max_tokens=64,
                output_tokens=12,
            )
        )

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_run_fidelity_uses_native_perplexity_binary(self, run_mock, which_mock):
        which_mock.side_effect = lambda name: "/opt/homebrew/bin/%s" % name
        run_mock.return_value = mock.Mock(returncode=0, stdout=_FAKE_PERPLEXITY_LOG, stderr="")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="standard",
            execution_mode="local_native",
            simulate=False,
        )
        fidelity = adapter.run_fidelity(request)
        self.assertEqual(fidelity.state, "measured")
        self.assertEqual(fidelity.metrics["perplexity"]["value"], 1.6244)
        self.assertEqual(run_mock.call_args[0][0][0], "/opt/homebrew/bin/llama-perplexity")

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_run_fidelity_perplexity_invalid_output_becomes_structured_failure(self, run_mock, which_mock):
        which_mock.side_effect = lambda name: "/opt/homebrew/bin/%s" % name
        run_mock.return_value = mock.Mock(returncode=1, stdout=b"perplexity output \xc4\n", stderr=b"fatal \xc4\n")
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="standard",
            execution_mode="local_native",
            simulate=False,
        )
        fidelity = adapter.run_fidelity(request)
        self.assertEqual(fidelity.state, "not_yet_measured")
        self.assertEqual(fidelity.reason_codes, ["perplexity_measurement_failed"])
        self.assertIn("perplexity output \ufffd", fidelity.artifacts["error"])
        self.assertIn("fatal \ufffd", fidelity.artifacts["error"])
        self.assertNotIn("UnicodeDecodeError", fidelity.artifacts["error"])
        self.assertNotIn("text", run_mock.call_args.kwargs)

    @mock.patch("infergrade.adapters.llama_cpp.docker_available", return_value=True)
    @mock.patch("infergrade.adapters.llama_cpp.install_image")
    @mock.patch("infergrade.adapters.llama_cpp._stop_container")
    @mock.patch("infergrade.adapters.llama_cpp._fetch_container_logs")
    @mock.patch("infergrade.adapters.llama_cpp._stream_server_completion")
    @mock.patch("infergrade.adapters.llama_cpp._wait_for_server_ready")
    @mock.patch("infergrade.adapters.llama_cpp._resolve_published_port")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_real_run_returns_completed_deployment_metrics(
        self,
        run_mock,
        _resolve_port_mock,
        wait_ready_mock,
        stream_mock,
        logs_mock,
        _stop_container_mock,
        _install_image_mock,
        _docker_mock,
    ):
        run_mock.return_value = mock.Mock(returncode=0, stdout="container-123\n", stderr="")
        _resolve_port_mock.return_value = 38080
        wait_ready_mock.return_value = ("http://127.0.0.1:38080", 1675.42)
        stream_mock.return_value = _FAKE_SERVER_COMPLETION
        logs_mock.return_value = _FAKE_SERVER_LOG
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            use_case="general_assistant",
            deployment_warmup_runs=0,
            deployment_measured_runs=2,
            simulate=False,
        )
        execution = adapter.run_deployment_profile(request, "interactive_chat_v1")
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.metrics["load_time_ms"], 1675.42)
        self.assertEqual(execution.metrics["ttft_p50_ms"], 2242.26)
        self.assertEqual(execution.metrics["prompt_tokens_per_second_p50"], 3.65)
        self.assertEqual(execution.metrics["decode_tokens_per_second_p50"], 6.63)
        self.assertEqual(execution.metrics["warmup_runs"], 0)
        self.assertEqual(execution.metrics["measured_runs"], 2)
        self.assertEqual(execution.metrics["output_tokens_p50"], 6.0)
        self.assertEqual(execution.metrics["token_budget_exhaustion_rate"], 0.0)
        self.assertFalse(execution.metrics["semantic_task_completion_proof"])
        self.assertIn("capability task-time", execution.metrics["completion_semantics"])
        self.assertIsNone(execution.metrics["peak_vram_mb"])
        self.assertEqual(len(execution.artifacts["runs"]), 2)
        command = execution.artifacts["runs"][0]["command"]
        self.assertEqual(command[0:2], ["docker", "run"])
        self.assertIn("ghcr.io/bfogels/infergrade-llama-cpp:%s" % __version__, command)
        self.assertIn("llama-server", command)

    def test_real_run_requires_local_gguf_artifact(self):
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact="hf://bartowski/qwen.gguf",
            backend="llama.cpp",
            tier="canary",
            simulate=False,
        )
        with self.assertRaises(ValueError):
            adapter.run_deployment_profile(request, "interactive_chat_v1")

    @mock.patch("infergrade.adapters.llama_cpp.docker_available", return_value=True)
    @mock.patch("infergrade.adapters.llama_cpp.install_image")
    @mock.patch("infergrade.adapters.llama_cpp._stop_container")
    @mock.patch("infergrade.adapters.llama_cpp._fetch_container_logs")
    @mock.patch("infergrade.adapters.llama_cpp._stream_server_completion")
    @mock.patch("infergrade.adapters.llama_cpp._wait_for_server_ready")
    @mock.patch("infergrade.adapters.llama_cpp._resolve_published_port")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_real_run_reports_iteration_progress(
        self,
        run_mock,
        _resolve_port_mock,
        wait_ready_mock,
        stream_mock,
        logs_mock,
        _stop_container_mock,
        _install_image_mock,
        _docker_mock,
    ):
        run_mock.return_value = mock.Mock(returncode=0, stdout="container-123\n", stderr="")
        _resolve_port_mock.return_value = 38080
        wait_ready_mock.return_value = ("http://127.0.0.1:38080", 1675.42)
        stream_mock.return_value = _FAKE_SERVER_COMPLETION
        logs_mock.return_value = _FAKE_SERVER_LOG
        adapter = LlamaCppAdapter()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            quant_artifact=self.model_path,
            backend="llama.cpp",
            tier="canary",
            use_case="general_assistant",
            simulate=False,
        )
        events = []
        adapter.run_deployment_profile(request, "interactive_chat_v1", progress_callback=events.append)
        event_types = [event["event"] for event in events]
        self.assertIn("profile_started", event_types)
        self.assertIn("iteration_started", event_types)
        self.assertIn("iteration_completed", event_types)


if __name__ == "__main__":
    unittest.main()
