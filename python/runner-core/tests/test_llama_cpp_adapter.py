import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.adapters.llama_cpp import (
    LlamaCppAdapter,
    _compute_ttft_ms,
    _parse_llama_timings,
    _safe_tokens_per_second,
)
from infergrade.container_runtime import ContainerCommandResult
from infergrade.models import RunRequest


_FAKE_TIMING_LOG = """
llama_print_timings:        load time =     617.57 ms
llama_print_timings: prompt eval time =     574.22 ms /    16 tokens (35.89 ms per token, 27.87 tokens per second)
llama_print_timings:        eval time =    1285.25 ms /    32 runs   (40.16 ms per token, 24.90 tokens per second)
llama_print_timings:       total time =    1901.48 ms /    48 tokens
"""

_FAKE_SUMMARY_LOG = """
[ Prompt: 65.2 t/s | Generation: 25.1 t/s ]
"""


class LlamaCppAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-llama-adapter-")
        self.model_path = os.path.join(self.tempdir.name, "model.gguf")
        with open(self.model_path, "w", encoding="utf-8") as handle:
            handle.write("fake gguf")

    def tearDown(self):
        self.tempdir.cleanup()

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
        command = run_mock.call_args[0][0]
        self.assertEqual(command[:4], ["docker", "run", "--rm", "--entrypoint"])

    @mock.patch("infergrade.adapters.llama_cpp.docker_available", return_value=True)
    @mock.patch("infergrade.adapters.llama_cpp.install_image")
    @mock.patch("infergrade.adapters.llama_cpp.run_command_with_optional_gpu_monitor")
    def test_real_run_returns_completed_deployment_metrics(self, run_mock, _install_image_mock, _docker_mock):
        run_mock.return_value = ContainerCommandResult(
            stdout="",
            stderr=_FAKE_TIMING_LOG,
            returncode=0,
            duration_seconds=2.0,
            peak_vram_mb=1536.0,
        )
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
        self.assertEqual(execution.metrics["load_time_ms"], 617.57)
        self.assertEqual(execution.metrics["ttft_p50_ms"], 614.38)
        self.assertEqual(execution.metrics["decode_tokens_per_second_p50"], 24.9)
        self.assertEqual(execution.metrics["peak_vram_mb"], 1536.0)
        self.assertEqual(len(execution.artifacts["runs"]), 2)
        command = execution.artifacts["runs"][0]["command"]
        self.assertEqual(command[0:3], ["docker", "run", "--rm"])
        self.assertIn("infergrade-llama-cpp:local", command)
        self.assertIn("/models/model.gguf", command)

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


if __name__ == "__main__":
    unittest.main()
