import unittest
import json
import os
import subprocess
import tempfile
from pathlib import Path
from infergrade.json_schema_subset import validate_json_schema
from unittest import mock

from infergrade.adapters.llama_cpp import (
    _DEFAULT_IMAGE, LlamaCppAdapter, native_cuda_required, _native_backend_flags, _require_native_cuda_offload,
    _supports_automatic_fit, _probe_automatic_fit,
)
from infergrade.models import RunRequest
from infergrade.runner import _enforce_runtime_selector_before_execution


class NativeCudaGuardsTests(unittest.TestCase):
    def request(self, api="unknown", system="linux"):
        return RunRequest(model="test/model", backend="llama.cpp", tier="canary",
                          execution_mode="local_native", simulate=False,
                          runtime_selector={"runtime_selector_version": "0.3", "platform": {"system": system},
                                            "accelerator": {"api": api},
                                            "delivery": {"binary_set": "llama_cpp_native_host_selected"}})

    @mock.patch("infergrade.adapters.llama_cpp.selected_llama_cpp_runtime",
                return_value={"accelerator": "cuda"})
    def test_generic_host_selector_binds_managed_cuda_and_preserves_explicit_cpu(self, selected):
        request = self.request()
        self.assertTrue(native_cuda_required(request))
        self.assertEqual(_native_backend_flags(request), ["--n-gpu-layers", "999", "--log-verbosity", "4"])
        cpu = self.request("cpu")
        self.assertFalse(native_cuda_required(cpu))
        self.assertEqual(_native_backend_flags(cpu), ["--n-gpu-layers", "0"])
        cpu.backend_flags = ["--n-gpu-layers=99"]
        self.assertEqual(_native_backend_flags(cpu)[-2:], ["--n-gpu-layers", "0"])
        custom = self.request()
        custom.llama_cpp_cli_path = "/custom/llama-cli"
        self.assertFalse(native_cuda_required(custom))

    @mock.patch("infergrade.adapters.llama_cpp.shutil.which", return_value="nvidia-smi")
    def test_nvidia_default_and_saved_flags_use_separate_argv(self, which):
        adapter = LlamaCppAdapter()
        self.assertEqual(adapter.default_backend_flags(), ["--n-gpu-layers", "99"])
        for mode in ("local_native", "local_container"):
            request = self.request("unknown")
            request.execution_mode = mode
            request.llama_cpp_cli_path = "/custom/llama-cli"
            request.backend_flags = ["--n-gpu-layers=99", "--other=value"]
            original = list(request.backend_flags)
            commands = [
                adapter._build_llama_cli_command("model.gguf", "hello", 8, 512, request),
                adapter._build_llama_server_command("model.gguf", 512, request),
                adapter._build_llama_perplexity_command("model.gguf", "corpus.txt", request),
            ]
            for command in commands:
                with self.subTest(mode=mode, command=command):
                    index = command.index("--n-gpu-layers")
                    self.assertEqual(command[index + 1], "99")
                    self.assertNotIn("--n-gpu-layers=99", command)
                    self.assertIn("--other=value", command)
            self.assertEqual(request.backend_flags, original)
        request.backend_flags = ["--n-gpu-layers", "42", "-ngl", "1"]
        self.assertEqual(_native_backend_flags(request), request.backend_flags)

    @mock.patch("infergrade.runner.windows_cuda_preflight")
    def test_new_linux_and_windows_cuda_packages_do_not_enter_legacy_windows_gate(self, preflight):
        for system in ("linux", "windows"):
            _enforce_runtime_selector_before_execution(self.request("cuda", system))
        preflight.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp._supports_automatic_fit", return_value=True)
    def test_supported_native_tools_fit_without_forced_layers_and_keep_context(self, supports):
        request = self.request("cuda")
        adapter = LlamaCppAdapter()
        with mock.patch.object(adapter, "_native_completion_path", return_value="completion"), \
             mock.patch.object(adapter, "_native_server_path", return_value="server"), \
             mock.patch.object(adapter, "_native_perplexity_path", return_value="perplexity"):
            commands = [
                adapter._build_llama_cli_command("model.gguf", "hello", 8, 8192, request),
                adapter._build_llama_server_command("model.gguf", 8192, request),
                adapter._build_llama_perplexity_command("model.gguf", "corpus.txt", request),
            ]
        self.assertEqual([call.args[0] for call in supports.call_args_list],
                         ["completion", "server", "perplexity"])
        for command, context in zip(commands, (8192, 8192, 128)):
            self.assertEqual(command[command.index("--fit") + 1], "on")
            self.assertEqual(command[command.index("-c") + 1], str(context))
            self.assertNotIn("--n-gpu-layers", command)
            self.assertIn("--log-verbosity", command)
        self.assertEqual(request.backend_flags, [])
        # Fitting does not weaken the positive CUDA evidence requirement.
        with self.assertRaisesRegex(RuntimeError, "CPU fallback"):
            _require_native_cuda_offload(request, "using device CPU\noffloaded 0/5 layers")

    @mock.patch("infergrade.adapters.llama_cpp._supports_automatic_fit")
    def test_fitting_preserves_explicit_flags_cpu_and_container(self, supports):
        adapter = LlamaCppAdapter()
        for flags in (["--fit", "off"], ["-ngl", "12"], ["--n-gpu-layers=12"],
                      ["--fit", "on", "--fit-target", "2048"]):
            request = self.request("cuda")
            request.backend_flags = list(flags)
            self.assertEqual(adapter._backend_flags(request, "server"),
                             _native_backend_flags(request))
        cpu = self.request("cpu")
        self.assertEqual(adapter._backend_flags(cpu, "server"), ["--n-gpu-layers", "0"])
        container = self.request()
        container.execution_mode = "local_container"
        container.backend_flags = ["--fit", "off"]
        self.assertEqual(adapter._backend_flags(container, "server"), container.backend_flags)
        supports.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp._supports_automatic_fit")
    def test_pinned_container_fits_but_custom_image_keeps_legacy_defaults(self, supports):
        adapter = LlamaCppAdapter()
        request = self.request()
        request.execution_mode = "local_container"
        with mock.patch.object(adapter, "_image_name", return_value=_DEFAULT_IMAGE):
            command = adapter._build_llama_server_command("model.gguf", 8192, request)
        self.assertEqual(command[command.index("--fit") + 1], "on")
        self.assertNotIn("--n-gpu-layers", command)
        request.backend_image = "custom/unknown:runtime"
        with mock.patch.object(adapter, "default_backend_flags", return_value=["--n-gpu-layers", "99"]):
            self.assertEqual(adapter._backend_flags(request, "server"), ["--n-gpu-layers", "99"])
        supports.assert_not_called()

    @mock.patch("infergrade.adapters.llama_cpp._supports_automatic_fit", return_value=False)
    def test_unsupported_native_keeps_legacy_cuda_default(self, supports):
        adapter = LlamaCppAdapter()
        with mock.patch.object(adapter, "_native_server_path", return_value="old-server"):
            self.assertEqual(adapter._backend_flags(self.request("cuda"), "server"),
                             ["--n-gpu-layers", "999", "--log-verbosity", "4"])

    def test_fit_help_probe_is_bounded_exact_and_cached_by_binary_identity(self):
        _probe_automatic_fit.cache_clear()
        with tempfile.NamedTemporaryFile() as binary:
            with mock.patch("infergrade.adapters.llama_cpp.subprocess.run") as run:
                run.return_value = mock.Mock(returncode=0, stdout=b"--fit [on|off]", stderr=b"")
                self.assertTrue(_supports_automatic_fit(binary.name))
                self.assertTrue(_supports_automatic_fit(binary.name))
                run.assert_called_once_with([os.path.realpath(binary.name), "--help"],
                                            capture_output=True, timeout=10)
                binary.write(b"new executable identity")
                binary.flush()
                run.return_value = mock.Mock(returncode=0, stdout=b"--fit-target MiB", stderr=b"")
                self.assertFalse(_supports_automatic_fit(binary.name))
                self.assertEqual(run.call_count, 2)
        for result in (mock.Mock(returncode=1, stdout=b"--fit on", stderr=b""),
                       subprocess.TimeoutExpired("help", 10), OSError("missing")):
            _probe_automatic_fit.cache_clear()
            with mock.patch("infergrade.adapters.llama_cpp.subprocess.run") as run:
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                self.assertFalse(_probe_automatic_fit("binary", 1, 1))
        _probe_automatic_fit.cache_clear()

    def test_linux_cuda_delivery_name_requires_cuda_even_with_unknown_accelerator(self):
        request = self.request()
        request.runtime_selector["delivery"]["binary_set"] = "llama_cpp_linux_cuda_x86_64"
        self.assertTrue(native_cuda_required(request))
        with self.assertRaisesRegex(RuntimeError, "CPU fallback"):
            _require_native_cuda_offload(request, "using device CPU\noffloaded 0/5 layers to GPU")

    def test_explicit_cuda_accepts_nonzero_device_offload_and_records_observed_probe(self):
        for marker in ("load: using device CUDA0 (NVIDIA test)", "load_tensors: CUDA0 model buffer size = 4 MiB"):
            request = self.request("cuda")
            _require_native_cuda_offload(request, marker + "\nload_tensors: offloaded 3/5 layers to GPU")
            self.assertEqual(request.runtime_selector["accelerator"]["vendor"], "nvidia")
            self.assertEqual(request.runtime_selector["compatibility"]["probes"][0]["observed"], "CUDA offloaded 3/5 layers")

    def test_explicit_cuda_rejects_cpu_zero_offload_and_missing_device(self):
        for logs in ("CPU model buffer\noffloaded 0/5 layers to GPU",
                     "using device CUDA0\noffloaded 0/5 layers to GPU",
                     "CPU model buffer\noffloaded 3/5 layers to GPU", ""):
            with self.subTest(logs=logs), self.assertRaisesRegex(RuntimeError, "CPU fallback is not accepted"):
                _require_native_cuda_offload(self.request("cuda"), logs)

    def test_observed_cuda_probe_preserves_the_runtime_selector_contract(self):
        request = self.request("cuda")
        selector = request.runtime_selector
        selector.update({"runtime_family": "llama.cpp",
                         "support": {"tier": "best_effort", "claim_boundary": "Exact native candidate only"},
                         "fallback": {"allowed": False, "mode": None, "reason": "No CPU fallback"},
                         "compatibility": {"status": "unknown", "reason_codes": [], "probes": []}})
        selector["platform"]["arch"] = "x86_64"
        selector["accelerator"]["vendor"] = "unknown"
        selector["delivery"].update({"mode": "managed_download", "source": "infergrade_runtime_manifest", "selected_by": "managed_recommendation"})
        _require_native_cuda_offload(request, "using device CUDA0\noffloaded 3/5 layers to GPU")
        schema_path = Path(__file__).resolve().parents[3] / "schemas/json/runtime_selector.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(validate_json_schema(selector, schema, schema_path), [])

    def test_direct_cli_does_not_gain_a_partial_runtime_selector(self):
        request = self.request()
        request.runtime_selector = {}
        request._locked_native_accelerator = "cuda"
        _require_native_cuda_offload(request, "using device CUDA0\noffloaded 3/5 layers to GPU")
        self.assertEqual(request.runtime_selector, {})
        self.assertEqual(request._native_cuda_offload_evidence, "CUDA offloaded 3/5 layers")

    def test_cuda_probe_cannot_clear_an_unrelated_compatibility_gate(self):
        request = self.request("cuda")
        request.runtime_selector["compatibility"] = {"status": "blocked", "reason_codes": ["architecture_not_qualified"], "probes": []}
        _require_native_cuda_offload(request, "using device CUDA0\noffloaded 3/5 layers to GPU")
        self.assertEqual(request.runtime_selector["compatibility"]["status"], "blocked")
        self.assertEqual(request.runtime_selector["compatibility"]["reason_codes"], ["architecture_not_qualified"])

    @mock.patch("infergrade.adapters.llama_cpp._stop_process")
    @mock.patch("infergrade.adapters.llama_cpp._read_log_file", return_value="CPU model buffer\noffloaded 0/5 layers to GPU")
    @mock.patch("infergrade.adapters.llama_cpp._wait_for_native_server_ready")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/managed/llama-server")
    @mock.patch.object(LlamaCppAdapter, "_require_local_gguf_artifact", return_value="/public/model.gguf")
    @mock.patch.object(LlamaCppAdapter, "_ensure_backend_model_compatibility")
    @mock.patch("infergrade.adapters.llama_cpp.selected_llama_cpp_runtime", return_value={"accelerator": "cuda"})
    def test_healthy_cpu_server_is_rejected_before_any_generation(self, selected, compatibility, model, server, popen, ready, logs, stop):
        adapter = LlamaCppAdapter()
        request = self.request()
        with self.assertRaisesRegex(RuntimeError, "CPU fallback is not accepted"):
            adapter.preflight_model(request)
        ready.assert_called_once()
        stop.assert_called_once_with(popen.return_value)
        self.assertIn("999", popen.call_args[0][0])
        self.assertNotIn("--n-gpu-layers=999", popen.call_args[0][0])
        self.assertNotIn("compatibility", request.runtime_selector)

    @mock.patch("infergrade.adapters.llama_cpp._stop_process")
    @mock.patch("infergrade.adapters.llama_cpp._read_log_file", return_value="using device CUDA0\noffloaded 3/5 layers to GPU")
    @mock.patch("infergrade.adapters.llama_cpp._wait_for_native_server_ready")
    @mock.patch("infergrade.adapters.llama_cpp.subprocess.Popen")
    @mock.patch.object(LlamaCppAdapter, "_native_server_path", return_value="/managed/llama-server")
    @mock.patch.object(LlamaCppAdapter, "_require_local_gguf_artifact", return_value="/public/model.gguf")
    @mock.patch.object(LlamaCppAdapter, "_ensure_backend_model_compatibility")
    def test_healthy_cuda_server_records_probe_before_execution(self, compatibility, model, server, popen, ready, logs, stop):
        request = self.request("cuda", "windows")
        LlamaCppAdapter().preflight_model(request)
        self.assertEqual(request.runtime_selector["compatibility"]["status"], "ready")
        self.assertEqual(request.runtime_selector["compatibility"]["probes"][0]["id"], "native_cuda_offload")


if __name__ == "__main__":
    unittest.main()
