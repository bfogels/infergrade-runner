import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.support import build_support_export, write_support_export


class SupportExportTests(unittest.TestCase):
    def test_build_support_export_sanitizes_runner_profile_and_detects_files(self):
        with tempfile.TemporaryDirectory(prefix="infergrade-support-") as tempdir:
            artifacts_dir = os.path.join(tempdir, "artifacts", "receipts")
            os.makedirs(artifacts_dir, exist_ok=True)
            with open(os.path.join(tempdir, "progress.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "current_stage": "deployment",
                        "request_context": {
                            "pair_code": "igrp_secret_pair",
                            "safe_detail": "interactive_chat_v1",
                        },
                    },
                    handle,
                )
            with open(os.path.join(tempdir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump({"bundle_id": "qb_bundle", "signed_url": "https://example.test/private?token=secret"}, handle)
            with open(os.path.join(tempdir, "artifacts", "environment.json"), "w", encoding="utf-8") as handle:
                json.dump({"hardware_class": "apple_silicon"}, handle)
            with open(os.path.join(artifacts_dir, "quant_artifact_resolution.json"), "w", encoding="utf-8") as handle:
                json.dump({"uri": "hf://example/model.gguf"}, handle)

            with mock.patch(
                    "infergrade.support.load_runner_profile",
                    return_value={
                        "api_url": "http://localhost:8000",
                        "access_token": "qbhr_secret_token",
                        "token_expires_at": "2026-05-20T00:00:00Z",
                        "label": "Brian MacBook Pro",
                    },
            ), mock.patch(
                "infergrade.support.capture_environment",
                return_value={"hardware_class": "apple_silicon", "execution_mode": "local_native"},
            ):
                payload = build_support_export(run_dir=tempdir, execution_mode="local_native")

        self.assertEqual(payload["export_kind"], "infergrade_runner_support_v1")
        self.assertEqual(payload["cuda"]["included"], False)
        self.assertEqual(payload["cuda"]["reason"], "no_cuda_signal")
        self.assertTrue(payload["secrets_excluded"])
        self.assertEqual(payload["runner_profile"]["access_token_present"], True)
        self.assertNotIn("access_token", payload["runner_profile"])
        self.assertNotIn("access_token_prefix", payload["runner_profile"])
        self.assertEqual(payload["runner_profile"]["token_expires_at"], "[redacted]")
        self.assertEqual(payload["environment"]["execution_mode"], "local_native")
        self.assertEqual(payload["summary"]["bundle_id"], "qb_bundle")
        self.assertEqual(payload["summary"]["signed_url"], "[redacted]")
        self.assertEqual(payload["progress"]["request_context"]["pair_code"], "[redacted]")
        self.assertEqual(payload["progress"]["request_context"]["safe_detail"], "interactive_chat_v1")
        self.assertTrue(payload["files_present"]["progress_json"])
        self.assertTrue(payload["files_present"]["artifact_receipt"])
        encoded = json.dumps(payload)
        self.assertNotIn("qbhr_secret_token", encoded)
        self.assertNotIn("igrp_secret_pair", encoded)
        self.assertNotIn("https://example.test/private", encoded)

    def test_build_support_export_redacts_nested_raw_outputs_and_signed_urls(self):
        with tempfile.TemporaryDirectory(prefix="infergrade-support-adversarial-") as tempdir:
            os.makedirs(os.path.join(tempdir, "artifacts"), exist_ok=True)
            with open(os.path.join(tempdir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "safe_id": "manifest-1",
                        "artifacts": [
                            {
                                "raw_outputs": ["PRIVATE MODEL OUTPUT"],
                                "nested": {
                                    "prompt": "PRIVATE PROMPT",
                                    "completion_text": "PRIVATE COMPLETION",
                                    "download_url": "https://storage.example/object?X-Amz-Signature=secret&X-Amz-Credential=secret",
                                },
                            }
                        ],
                    },
                    handle,
                )

            with mock.patch("infergrade.support.load_runner_profile", return_value=None), mock.patch(
                "infergrade.support.capture_environment",
                return_value={"hardware_class": "apple_silicon", "execution_mode": "local_native"},
            ):
                payload = build_support_export(run_dir=tempdir, execution_mode="local_native")

        artifact = payload["manifest"]["artifacts"][0]
        self.assertEqual(payload["manifest"]["safe_id"], "manifest-1")
        self.assertEqual(artifact["raw_outputs"], "[redacted]")
        self.assertEqual(artifact["nested"]["prompt"], "[redacted]")
        self.assertEqual(artifact["nested"]["completion_text"], "[redacted]")
        self.assertEqual(artifact["nested"]["download_url"], "[redacted]")
        encoded = json.dumps(payload)
        self.assertNotIn("PRIVATE MODEL OUTPUT", encoded)
        self.assertNotIn("PRIVATE PROMPT", encoded)
        self.assertNotIn("PRIVATE COMPLETION", encoded)
        self.assertNotIn("X-Amz-Signature", encoded)

    def test_build_support_export_includes_cuda_preflight_for_nvidia_environment(self):
        with tempfile.TemporaryDirectory(prefix="infergrade-support-cuda-") as tempdir:
            cuda_preflight = {
                "selector": {
                    "platform": {"system": "windows", "arch": "amd64", "version": "windows-10"},
                    "accelerator": {"api": "cuda", "vendor": "nvidia"},
                    "driver": {"version": "555.85", "minimum_required": "525.0", "cuda_major": "12"},
                    "delivery": {"source": "explicit_path", "binary_set": "llama_cpp_windows_cuda_x86_64"},
                    "binary": {"path": "C:\\llama.cpp\\llama-cli.exe", "version_output": "llama.cpp build 1234"},
                    "compatibility": {"status": "blocked", "reason_codes": ["full_loop_not_proven", "fallback_not_allowed"]},
                },
                "gpu_count": 1,
                "hardware_blocked": True,
                "next_action": "Validate on a Windows/NVIDIA machine before enabling evidence-producing technical beta.",
                "proof_gate": {
                    "status": "blocked",
                    "reason_code": "full_loop_not_proven",
                    "required_steps": [
                        {"id": "select_runtime"},
                        {"id": "pair_hub_runner"},
                        {"id": "known_good_gguf_run"},
                        {"id": "upload_result"},
                        {"id": "review_result"},
                        {"id": "capture_support_export"},
                    ],
                },
            }
            environment = {
                "hardware_class": "nvidia_gpu",
                "accelerator_vendor": "nvidia",
                "accelerator_api": "cuda",
                "driver_versions": {"cuda": "12.5", "nvidia": "555.85"},
                "cpu_architecture": "AMD64",
                "os": "windows-10",
            }
            with mock.patch("infergrade.support.load_runner_profile", return_value=None), mock.patch(
                "infergrade.support.capture_environment",
                return_value=environment,
            ), mock.patch(
                "infergrade.support.windows_cuda_preflight",
                return_value=cuda_preflight,
            ) as preflight_mock, mock.patch.dict(
                os.environ,
                {"INFERGRADE_LLAMA_CPP_CUDA_CLI": "C:\\llama.cpp\\llama-cli.exe"},
                clear=False,
            ):
                payload = build_support_export(run_dir=tempdir, execution_mode="local_native")

        self.assertTrue(payload["cuda"]["included"])
        self.assertEqual(payload["cuda"]["reason"], "nvidia_cuda_environment")
        self.assertEqual(payload["cuda"]["preflight"], cuda_preflight)
        self.assertEqual(payload["cuda"]["summary"]["status"], "blocked")
        self.assertEqual(payload["cuda"]["summary"]["gpu_count"], 1)
        self.assertEqual(payload["cuda"]["summary"]["platform"]["system"], "windows")
        self.assertEqual(payload["cuda"]["summary"]["runtime"]["source"], "explicit_path")
        self.assertEqual(payload["cuda"]["summary"]["runtime"]["binary_path_present"], True)
        self.assertEqual(payload["cuda"]["summary"]["runtime"]["version_output"], "llama.cpp build 1234")
        self.assertIn("full_loop_not_proven", payload["cuda"]["summary"]["reason_codes"])
        self.assertIn("Windows/NVIDIA machine", payload["cuda"]["summary"]["next_action"])
        self.assertEqual(payload["cuda"]["summary"]["proof_gate"]["status"], "blocked")
        self.assertEqual(
            payload["cuda"]["summary"]["proof_gate"]["required_step_ids"],
            [
                "select_runtime",
                "pair_hub_runner",
                "known_good_gguf_run",
                "upload_result",
                "review_result",
                "capture_support_export",
            ],
        )
        preflight_mock.assert_called_once_with(
            runtime_binary_path="C:\\llama.cpp\\llama-cli.exe",
            cuda_major="12",
            platform_snapshot={"system": "windows", "arch": "amd64", "version": "windows-10"},
        )

    def test_build_support_export_includes_selected_cuda_runtime_preflight(self):
        with tempfile.TemporaryDirectory(prefix="infergrade-support-cuda-selected-") as tempdir:
            cuda_preflight = {
                "selector": {
                    "platform": {"system": "windows", "arch": "amd64", "version": "windows-11"},
                    "accelerator": {"api": "cuda", "vendor": "unknown"},
                    "driver": {"version": None, "minimum_required": "525.0", "cuda_major": "12"},
                    "delivery": {"source": "explicit_path", "binary_set": "llama_cpp_windows_cuda_x86_64"},
                    "binary": {"path": "C:\\llama.cpp\\llama-cli.exe", "version_output": None},
                    "compatibility": {"status": "blocked", "reason_codes": ["nvidia_smi_missing", "full_loop_not_proven"]},
                },
                "gpu_count": 0,
                "hardware_blocked": True,
                "next_action": "Run CUDA preflight on the selected Windows/NVIDIA host.",
                "proof_gate": {
                    "status": "blocked",
                    "reason_code": "full_loop_not_proven",
                    "required_steps": [{"id": "select_runtime"}],
                },
            }
            environment = {
                "hardware_class": "cpu_only",
                "accelerator_vendor": None,
                "accelerator_api": None,
                "driver_versions": {},
                "cpu_architecture": "AMD64",
                "os": "windows-11",
            }
            selected_runtime = {
                "runtime_id": "llama-cpp-windows-cuda-cli-preview-2026-05",
                "binary_set": "llama_cpp_windows_cuda_x86_64",
                "binaries": {"cli": "C:\\llama.cpp\\llama-cli.exe"},
            }
            with mock.patch("infergrade.support.load_runner_profile", return_value=None), mock.patch(
                "infergrade.support.capture_environment",
                return_value=environment,
            ), mock.patch(
                "infergrade.support.selected_llama_cpp_runtime",
                return_value=selected_runtime,
            ), mock.patch(
                "infergrade.support.windows_cuda_preflight",
                return_value=cuda_preflight,
            ) as preflight_mock, mock.patch.dict(
                os.environ,
                {},
                clear=True,
            ):
                payload = build_support_export(run_dir=tempdir, execution_mode="local_native")

        self.assertTrue(payload["cuda"]["included"])
        self.assertEqual(payload["cuda"]["reason"], "selected_cuda_runtime")
        self.assertEqual(payload["cuda"]["summary"]["runtime"]["binary_path_present"], True)
        self.assertIn("nvidia_smi_missing", payload["cuda"]["summary"]["reason_codes"])
        preflight_mock.assert_called_once_with(
            runtime_binary_path="C:\\llama.cpp\\llama-cli.exe",
            cuda_major="12",
            platform_snapshot={"system": "windows", "arch": "amd64", "version": "windows-11"},
        )

    def test_build_support_export_ignores_non_cuda_selected_runtime_signal(self):
        with mock.patch("infergrade.support.load_runner_profile", return_value=None), mock.patch(
            "infergrade.support.capture_environment",
            return_value={
                "hardware_class": "cpu_only",
                "accelerator_vendor": None,
                "accelerator_api": None,
                "driver_versions": {},
                "cpu_architecture": "x86_64",
                "os": "linux-6.0",
            },
        ), mock.patch(
            "infergrade.support.selected_llama_cpp_runtime",
            return_value={
                "runtime_id": "llama-cpp-homebrew-stable-2026-04",
                "binaries": {"cli": "/opt/homebrew/bin/llama-cli"},
            },
        ), mock.patch(
            "infergrade.support.windows_cuda_preflight",
        ) as preflight_mock, mock.patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            payload = build_support_export(execution_mode="local_native")

        self.assertFalse(payload["cuda"]["included"])
        self.assertEqual(payload["cuda"]["reason"], "no_cuda_signal")
        preflight_mock.assert_not_called()

    def test_write_support_export_writes_json_payload(self):
        with tempfile.TemporaryDirectory(prefix="infergrade-support-output-") as tempdir:
            output_path = os.path.join(tempdir, "support.json")
            with mock.patch(
                "infergrade.support.build_support_export",
                return_value={"export_kind": "infergrade_runner_support_v1"},
            ):
                written = write_support_export(output_path, execution_mode="local_native")

            self.assertEqual(written, output_path)
            with open(output_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["export_kind"], "infergrade_runner_support_v1")


if __name__ == "__main__":
    unittest.main()
