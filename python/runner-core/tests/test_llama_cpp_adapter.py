import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.adapters.llama_cpp import (
    LlamaCppAdapter,
    _compute_ttft_ms,
    _decode_utf8_lossy,
    _fetch_container_logs,
    _llama_generation_protocol_error,
    _metrics_from_server_completion,
    _parse_llama_memory_allocations,
    _parse_llama_timings,
    _parse_perplexity_output,
    _read_log_file,
    _read_gguf_architecture,
    _safe_tokens_per_second,
    _sample_container_cgroup_memory,
    _sample_process_rss_mb,
    _start_container_memory_monitor,
    _stop_container_memory_monitor,
)
from infergrade.models import RunRequest
from infergrade.runtimes import select_llama_cpp_runtime


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
        select_llama_cpp_runtime(cli_path="/managed/llama-cli", server_path="/managed/llama-server")
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
    def test_resolve_version_rejects_unsupported_gemma4_architecture_early(self, run_mock):
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
        with self.assertRaisesRegex(RuntimeError, "GGUF architecture 'gemma4'"):
            adapter.resolve_version(simulate=False, request=request)
        run_mock.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp.subprocess.run")
    def test_resolve_version_rejects_unsupported_architecture_from_gguf_metadata(self, run_mock):
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
        with self.assertRaisesRegex(RuntimeError, "GGUF architecture 'gemma4'"):
            adapter.resolve_version(simulate=False, request=request)
        run_mock.assert_not_called()

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
            simulate=False,
        )
        execution = adapter.run_deployment_profile(request, "interactive_chat_v1")
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.metrics["load_time_ms"], 1675.42)
        self.assertEqual(execution.metrics["ttft_p50_ms"], 2242.26)
        self.assertEqual(execution.metrics["prompt_tokens_per_second_p50"], 3.65)
        self.assertEqual(execution.metrics["decode_tokens_per_second_p50"], 6.63)
        self.assertIsNone(execution.metrics["peak_vram_mb"])
        self.assertEqual(len(execution.artifacts["runs"]), 2)
        command = execution.artifacts["runs"][0]["command"]
        self.assertEqual(command[0:2], ["docker", "run"])
        self.assertIn("infergrade-llama-cpp:local", command)
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
