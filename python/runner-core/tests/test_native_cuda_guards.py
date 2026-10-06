import unittest
from unittest import mock

from infergrade.adapters.llama_cpp import (
    LlamaCppAdapter, native_cuda_required, _native_backend_flags, _require_native_cuda_offload,
)
from infergrade.models import RunRequest
from infergrade.runner import _enforce_runtime_selector_before_execution


class NativeCudaGuardsTests(unittest.TestCase):
    def request(self, api="unknown", system="linux"):
        return RunRequest(model="test/model", backend="llama.cpp", tier="canary",
                          execution_mode="local_native", simulate=False,
                          runtime_selector={"platform": {"system": system},
                                            "accelerator": {"api": api},
                                            "delivery": {"binary_set": "llama_cpp_native_host_selected"}})

    @mock.patch("infergrade.adapters.llama_cpp.selected_llama_cpp_runtime",
                return_value={"accelerator": "cuda"})
    def test_generic_host_selector_binds_managed_cuda_and_preserves_explicit_cpu(self, selected):
        request = self.request()
        self.assertTrue(native_cuda_required(request))
        self.assertEqual(_native_backend_flags(request), ["--n-gpu-layers=999"])
        cpu = self.request("cpu")
        self.assertFalse(native_cuda_required(cpu))
        self.assertEqual(_native_backend_flags(cpu), ["--n-gpu-layers=0"])
        custom = self.request()
        custom.llama_cpp_cli_path = "/custom/llama-cli"
        self.assertFalse(native_cuda_required(custom))

    @mock.patch("infergrade.runner.windows_cuda_preflight")
    def test_new_linux_and_windows_cuda_packages_do_not_enter_legacy_windows_gate(self, preflight):
        for system in ("linux", "windows"):
            _enforce_runtime_selector_before_execution(self.request("cuda", system))
        preflight.assert_not_called()

    def test_explicit_cuda_accepts_nonzero_device_offload_and_records_observed_probe(self):
        for marker in ("load: using device CUDA0 (NVIDIA test)", "load_tensors: CUDA0 model buffer size = 4 MiB"):
            request = self.request("cuda")
            _require_native_cuda_offload(request, marker + "\nload_tensors: offloaded 3/5 layers to GPU")
            self.assertEqual(request.runtime_selector["accelerator"]["vendor"], "nvidia")
            self.assertEqual(request.runtime_selector["compatibility"]["probes"][0]["observed"]["offloaded_layers"], 3)

    def test_explicit_cuda_rejects_cpu_zero_offload_and_missing_device(self):
        for logs in ("CPU model buffer\noffloaded 0/5 layers to GPU",
                     "using device CUDA0\noffloaded 0/5 layers to GPU",
                     "CPU model buffer\noffloaded 3/5 layers to GPU", ""):
            with self.subTest(logs=logs), self.assertRaisesRegex(RuntimeError, "CPU fallback is not accepted"):
                _require_native_cuda_offload(self.request("cuda"), logs)

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
        self.assertIn("--n-gpu-layers=999", popen.call_args[0][0])
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
