import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.doctor import run_doctor
from infergrade.models import RunRequest


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-doctor-")

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
