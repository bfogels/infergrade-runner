import sys
import json
import os
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.environment import _detect_apple_silicon_gpu, _detect_nvidia_gpu, capture_environment


class EnvironmentTests(unittest.TestCase):
    def test_detect_nvidia_gpu_parses_name_and_vram(self):
        with mock.patch("infergrade.environment._run_command", return_value="NVIDIA RTX 4090, 24564\n"):
            gpu = _detect_nvidia_gpu()
        self.assertEqual(gpu["accelerator_vendor"], "nvidia")
        self.assertEqual(gpu["accelerator_model"], "NVIDIA RTX 4090")
        self.assertEqual(gpu["accelerator_vram_gb"], 23.99)

    def test_detect_apple_silicon_gpu_uses_system_profiler(self):
        payload = """
        {
          "SPDisplaysDataType": [
            {
              "_name": "Apple M1 Pro",
              "spdisplays_vendor": "sppci_vendor_Apple",
              "sppci_device_type": "spdisplays_gpu",
              "sppci_model": "Apple M1 Pro",
              "sppci_cores": "16"
            }
          ],
          "SPHardwareDataType": [
            {
              "chip_type": "Apple M1 Pro",
              "machine_model": "MacBookPro18,3",
              "physical_memory": "16 GB"
            }
          ]
        }
        """.strip()
        with mock.patch("infergrade.environment.platform.system", return_value="Darwin"):
            with mock.patch("infergrade.environment._run_command", return_value=payload):
                gpu = _detect_apple_silicon_gpu()
        self.assertEqual(gpu["accelerator_vendor"], "apple")
        self.assertEqual(gpu["accelerator_model"], "Apple M1 Pro")
        self.assertEqual(gpu["accelerator_vram_gb"], 16.0)
        self.assertEqual(gpu["machine_model"], "MacBookPro18,3")

    def test_capture_environment_prefers_detected_accelerator(self):
        with mock.patch(
            "infergrade.environment._detect_nvidia_gpu",
            return_value={
                "accelerator_type": "gpu",
                "accelerator_vendor": "nvidia",
                "accelerator_model": "NVIDIA RTX 4090",
                "accelerator_vram_gb": 24.0,
                "accelerator_count": 1,
            },
        ):
            with mock.patch("infergrade.environment._detect_apple_silicon_gpu", return_value=None):
                with mock.patch("infergrade.environment._detect_cpu_model", return_value="Test CPU"):
                    with mock.patch("infergrade.environment._detect_memory_gb", return_value=64.0):
                        payload = capture_environment("cloud_container")
        self.assertEqual(payload["environment_class"], "cloud_vm")
        self.assertEqual(payload["accelerator_model"], "NVIDIA RTX 4090")
        self.assertEqual(payload["memory_gb"], 64.0)
        self.assertTrue(payload["hardware_id"].startswith("hw_"))

    def test_capture_environment_merges_host_override_snapshot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            snapshot_path = os.path.join(tempdir, "host-environment.json")
            with open(snapshot_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "accelerator_type": "gpu",
                        "accelerator_vendor": "apple",
                        "accelerator_model": "Apple M4 Max",
                        "accelerator_vram_gb": 48.0,
                        "accelerator_count": 1,
                        "cpu_model": "Apple M4 Max",
                        "memory_gb": 48.0,
                        "os": "darwin-25.0.0",
                        "machine_model": "Mac16,7",
                    },
                    handle,
                )
            with mock.patch.dict("os.environ", {"INFERGRADE_HOST_ENVIRONMENT_PATH": snapshot_path}, clear=False):
                with mock.patch("infergrade.environment._detect_nvidia_gpu", return_value=None):
                    with mock.patch("infergrade.environment._detect_apple_silicon_gpu", return_value=None):
                        with mock.patch("infergrade.environment._detect_cpu_model", return_value="linux-guest"):
                            with mock.patch("infergrade.environment._detect_memory_gb", return_value=8.0):
                                payload = capture_environment("local_container")
        self.assertEqual(payload["accelerator_model"], "Apple M4 Max")
        self.assertEqual(payload["accelerator_vram_gb"], 48.0)
        self.assertEqual(payload["cpu_model"], "Apple M4 Max")
        self.assertEqual(payload["memory_gb"], 48.0)
        self.assertEqual(payload["environment_class"], "local_workstation")


if __name__ == "__main__":
    unittest.main()
