import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.doctor import collect_runner_diagnostics, run_doctor
from infergrade.models import RunRequest


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-doctor-")
        self.env_patch = mock.patch.dict(os.environ, {"INFERGRADE_RUNTIME_CACHE_DIR": self.tempdir.name})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tempdir.cleanup()

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.urllib_request.urlopen")
    @mock.patch("infergrade.doctor.shutil.which")
    @mock.patch("infergrade.doctor.subprocess.run")
    def test_doctor_reports_ready_remote_run(self, run_mock, which_mock, urlopen_mock, capture_environment_mock):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "accelerator_type": "unknown",
            "accelerator_count": 0,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: "/usr/bin/%s" % name if name in ("docker", "curl") else None

        def fake_run(command, capture_output, text):
            if command[:2] == ["docker", "info"]:
                return mock.Mock(returncode=0, stdout="Server Version: 26.0.0", stderr="")
            if command[:3] == ["docker", "image", "inspect"]:
                return mock.Mock(returncode=0, stdout="[]", stderr="")
            raise AssertionError("Unexpected command: %r" % (command,))

        run_mock.side_effect = fake_run
        response = mock.MagicMock()
        response.read.return_value = b'{"ok": true}'
        urlopen_mock.return_value.__enter__.return_value = response

        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            quant_artifact_cache_dir=os.path.join(self.tempdir.name, "cache"),
            backend_image="infergrade-llama-cpp:local",
            output_dir=os.path.join(self.tempdir.name, "runs", "tiny"),
            execution_mode="local_container",
            run_config_id="rcfg_test",
        )
        report = run_doctor(request=request, api_url="http://localhost:8000")
        self.assertTrue(report["ok"])
        self.assertEqual(report["error_count"], 0)
        statuses = {item["id"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["api_health"], "ok")
        self.assertEqual(statuses["docker_daemon"], "ok")
        self.assertEqual(statuses["backend_image"], "ok")
        self.assertEqual(statuses["quant_artifact"], "ok")
        self.assertEqual(statuses["artifact_cache_dir"], "ok")
        self.assertEqual(statuses["output_dir"], "ok")
        checks = {item["id"]: item for item in report["checks"]}
        self.assertIn("free_bytes", checks["artifact_cache_dir"]["details"])
        self.assertIn("total_bytes", checks["artifact_cache_dir"]["details"])
        self.assertIn("min_required_free_bytes", checks["output_dir"]["details"])

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    def test_doctor_fails_when_local_artifact_missing_and_docker_absent(self, which_mock, capture_environment_mock):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "accelerator_type": "unknown",
            "accelerator_count": 0,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: None
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=os.path.join(self.tempdir.name, "missing.gguf"),
            backend_image="infergrade-llama-cpp:local",
            execution_mode="local_container",
        )
        report = run_doctor(request=request)
        self.assertFalse(report["ok"])
        statuses = {item["id"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["docker_cli"], "error")
        self.assertEqual(statuses["quant_artifact"], "error")

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    def test_doctor_flags_apple_silicon_container_real_run_as_cpu_fallback(self, which_mock, capture_environment_mock):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "hardware_class": "apple_silicon",
            "accelerator_api": "metal",
            "accelerator_type": "gpu",
            "accelerator_count": 1,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: None
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
            execution_mode="local_container",
            simulate=False,
        )
        report = run_doctor(request=request)
        statuses = {item["id"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["apple_silicon_local_container"], "error")

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    def test_doctor_checks_native_llama_binaries_for_local_native(self, which_mock, capture_environment_mock):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "hardware_class": "apple_silicon",
            "accelerator_api": "metal",
            "accelerator_type": "gpu",
            "accelerator_count": 1,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: "/opt/homebrew/bin/%s" % name if name in ("llama-cli", "llama-server") else None
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=os.path.join(self.tempdir.name, "missing.gguf"),
            execution_mode="local_native",
            simulate=False,
        )
        report = run_doctor(request=request)
        statuses = {item["id"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["llama_cli_native"], "ok")
        self.assertEqual(statuses["llama_server_native"], "ok")
        checks = {item["id"]: item for item in report["checks"]}
        self.assertIn(checks["llama_cli_native"]["details"]["version_status"], ("detected", "unknown"))

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    def test_doctor_reports_custom_native_llama_paths(self, which_mock, capture_environment_mock):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "hardware_class": "apple_silicon",
            "accelerator_api": "metal",
            "accelerator_type": "gpu",
            "accelerator_count": 1,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: name if name in ("/custom/llama-cli", "/custom/llama-server") else None
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=os.path.join(self.tempdir.name, "missing.gguf"),
            execution_mode="local_native",
            llama_cpp_cli_path="/custom/llama-cli",
            llama_cpp_server_path="/custom/llama-server",
            simulate=False,
        )
        report = run_doctor(request=request)
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(checks["llama_cli_native"]["details"]["source"], "custom_path")
        self.assertEqual(checks["llama_cli_native"]["details"]["requested"], "/custom/llama-cli")
        self.assertEqual(checks["llama_server_native"]["details"]["source"], "custom_path")

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    def test_doctor_fails_unsupported_llama_architecture_before_execution(self, which_mock, capture_environment_mock):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "hardware_class": "nvidia_gpu",
            "accelerator_api": "cuda",
            "accelerator_type": "gpu",
            "accelerator_count": 1,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: None
        request = RunRequest(
            model="google/gemma-4-27b-it",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://example/gemma4.gguf",
            execution_mode="local_container",
            ontology_hints={"architecture": "gemma4"},
            simulate=False,
        )
        report = run_doctor(request=request)
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(checks["llama_cpp_model_compatibility"]["status"], "error")
        self.assertIn("GGUF architecture 'gemma4'", checks["llama_cpp_model_compatibility"]["message"])

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    @mock.patch("infergrade.doctor.shutil.disk_usage")
    def test_doctor_fails_when_artifact_cache_is_below_free_space_floor(
        self,
        disk_usage_mock,
        which_mock,
        capture_environment_mock,
    ):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "accelerator_type": "unknown",
            "accelerator_count": 0,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: None
        disk_usage_mock.return_value = mock.Mock(free=1024)
        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            quant_artifact_cache_dir=os.path.join(self.tempdir.name, "cache"),
            output_dir=os.path.join(self.tempdir.name, "runs", "tiny"),
            execution_mode="local_native",
            simulate=False,
        )
        with mock.patch.dict(os.environ, {"INFERGRADE_MIN_ARTIFACT_CACHE_FREE_GB": "1", "INFERGRADE_MIN_OUTPUT_FREE_GB": "0"}, clear=False):
            report = run_doctor(request=request)
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(checks["artifact_cache_dir"]["status"], "error")
        self.assertEqual(checks["artifact_cache_dir"]["message"], "Insufficient free disk space.")
        self.assertEqual(checks["artifact_cache_dir"]["details"]["min_required_free_bytes"], 1024 ** 3)

    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    @mock.patch("infergrade.doctor.shutil.disk_usage")
    def test_doctor_fails_when_output_dir_is_below_free_space_floor(
        self,
        disk_usage_mock,
        which_mock,
        capture_environment_mock,
    ):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "accelerator_type": "unknown",
            "accelerator_count": 0,
            "hardware_id": "hw_test",
        }
        which_mock.side_effect = lambda name: None
        disk_usage_mock.return_value = mock.Mock(free=1024)
        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=os.path.join(self.tempdir.name, "model.gguf"),
            output_dir=os.path.join(self.tempdir.name, "runs", "tiny"),
            execution_mode="local_native",
            simulate=False,
        )
        with open(request.quant_artifact, "wb") as handle:
            handle.write(b"gguf")
        with mock.patch.dict(os.environ, {"INFERGRADE_MIN_OUTPUT_FREE_GB": "1"}, clear=False):
            report = run_doctor(request=request)
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(checks["output_dir"]["status"], "error")
        self.assertEqual(checks["output_dir"]["message"], "Insufficient free disk space.")
        self.assertEqual(checks["output_dir"]["details"]["min_required_free_bytes"], 1024 ** 3)

    @mock.patch("infergrade.doctor.load_contract_manifest")
    @mock.patch("infergrade.doctor.capture_environment")
    @mock.patch("infergrade.doctor.shutil.which")
    @mock.patch("infergrade.doctor.docker_image_exists")
    @mock.patch("infergrade.doctor.subprocess.run")
    def test_collect_runner_diagnostics_reports_blockers_and_warnings(
        self,
        run_mock,
        docker_image_exists_mock,
        which_mock,
        capture_environment_mock,
        load_contract_manifest_mock,
    ):
        capture_environment_mock.return_value = {
            "environment_class": "local_workstation",
            "hardware_class": "apple_silicon",
            "accelerator_api": "metal",
            "accelerator_type": "gpu",
            "accelerator_count": 1,
            "hardware_id": "hw_test",
        }
        load_contract_manifest_mock.return_value = {"publisher": "infergrade-runner", "contract_version": "0.1.0"}
        which_mock.side_effect = lambda name: "/usr/bin/docker" if name == "docker" else None
        docker_image_exists_mock.return_value = False
        run_mock.return_value = mock.Mock(returncode=0, stdout="Server Version: 26.0.0", stderr="")

        diagnostics = collect_runner_diagnostics(["local_container"])

        self.assertEqual(diagnostics["contract"]["contract_version"], "0.1.0")
        self.assertEqual(diagnostics["diagnostics"]["status"], "warning")
        check_statuses = {item["id"]: item["status"] for item in diagnostics["diagnostics"]["checks"]}
        self.assertEqual(check_statuses["docker_cli"], "ok")
        self.assertEqual(check_statuses["docker_daemon"], "ok")
        self.assertEqual(check_statuses["apple_silicon_local_container_warning"], "warning")
        self.assertEqual(check_statuses["local_image_llama_cpp"], "warning")


if __name__ == "__main__":
    unittest.main()
