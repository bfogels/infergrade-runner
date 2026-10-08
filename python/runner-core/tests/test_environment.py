import sys
import json
import os
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.environment import (
    _detect_amd_gpu,
    _detect_apple_silicon_fallback,
    _detect_apple_silicon_gpu,
    _detect_cpu_architecture,
    _detect_cpu_model,
    _detect_machine_model,
    _hardware_label,
    _windows_model,
    _windows_model_probe,
    _windows_registry_model,
    _detect_nvidia_gpu,
    _detect_process_translation,
    _detect_vulkan_gpu,
    capture_environment,
)


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        # Synthetic cross-platform cases must not read the actual Windows CI host.
        patcher = mock.patch('infergrade.environment._windows_registry_model', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_linux_cpu_and_machine_names_use_reported_fields_only(self):
        data = {"/proc/cpuinfo": "processor: 0\nmodel name: AMD Ryzen 9 7950X\nSerial: private-serial", "/sys/devices/virtual/dmi/id/product_name": "Precision 3660\n"}
        with mock.patch("infergrade.environment.platform.system", return_value="Linux"), mock.patch("infergrade.environment._read_hardware_text", side_effect=lambda path, *args: data.get(path)), mock.patch("infergrade.environment._run_command") as command:
            self.assertEqual(_detect_cpu_model(), "AMD Ryzen 9 7950X")
            self.assertEqual(_detect_machine_model(), "Precision 3660")
            command.assert_not_called()

    def test_linux_missing_dmi_uses_device_tree_and_missing_identity_stays_none(self):
        with mock.patch("infergrade.environment.platform.system", return_value="Linux"), mock.patch("infergrade.environment._read_hardware_text", side_effect=lambda path, *args: "Raspberry Pi 5 Model B\x00" if path == "/proc/device-tree/model" else "To Be Filled By O.E.M."):
            self.assertEqual(_detect_machine_model(), "Raspberry Pi 5 Model B")
        with mock.patch("infergrade.environment.platform.system", return_value="Linux"), mock.patch("infergrade.environment._read_hardware_text", return_value=None):
            self.assertIsNone(_detect_machine_model())

    def test_windows_model_queries_are_bounded_and_exclude_serials(self):
        with mock.patch("infergrade.environment.platform.system", return_value="Windows"), mock.patch("infergrade.environment.subprocess.run", return_value=mock.Mock(stdout="Precision 3660\n")) as run:
            self.assertEqual(_detect_machine_model(), "Precision 3660")
            args, kwargs = run.call_args
            self.assertIn("Win32_ComputerSystem", args[0][-1])
            self.assertTrue(args[0][-1].endswith(".Model"))
            self.assertEqual(kwargs["timeout"], 5)
        with mock.patch("infergrade.environment.subprocess.run", side_effect=OSError("unavailable")):
            self.assertIsNone(_windows_model("Win32_Processor", "Name"))

    def test_windows_unreadable_output_preserves_missing_identity(self):
        failure = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid OEM output")
        with mock.patch("infergrade.environment.subprocess.run", side_effect=failure):
            self.assertIsNone(_windows_model("Win32_ComputerSystem", "Model"))

    def test_windows_probe_diagnostics_are_bounded_codes_without_error_text(self):
        import subprocess
        for error, status in [(subprocess.TimeoutExpired('fixed probe', 5, output='private output'), 'timeout'),
                              (OSError('private failure'), 'command_unavailable'),
                              (UnicodeError('private output'), 'unreadable_output')]:
            with mock.patch('infergrade.environment.subprocess.run', side_effect=error):
                self.assertEqual(_windows_model_probe('Win32_ComputerSystem', 'Model'),
                                 {'status': status, 'value': None})
        with mock.patch('infergrade.environment.subprocess.run', return_value=mock.Mock(stdout='Default string')):
            self.assertEqual(_windows_model_probe('Win32_ComputerSystem', 'Model'),
                             {'status': 'missing_or_placeholder', 'value': None})

    def test_hardware_labels_reject_placeholders_controls_and_excessive_length(self):
        for label in [None, "unknown", "Default string", "System Product Name", "Bad\nName", "Bad\u0085Name", "x" * 257]:
            self.assertIsNone(_hardware_label(label))
        self.assertEqual(_hardware_label(" Dell Precision \n"), "Dell Precision")

    def test_detect_nvidia_gpu_parses_name_and_vram(self):
        with mock.patch("infergrade.environment._run_command", return_value="NVIDIA RTX 4090, 24564\n"):
            gpu = _detect_nvidia_gpu()
        self.assertEqual(gpu["hardware_class"], "nvidia_gpu")
        self.assertEqual(gpu["accelerator_api"], "cuda")
        self.assertEqual(gpu["accelerator_vendor"], "nvidia")
        self.assertEqual(gpu["accelerator_model"], "NVIDIA RTX 4090")
        self.assertEqual(gpu["accelerator_vram_gb"], 23.99)

    def test_detect_amd_gpu_parses_rocm_smi_json(self):
        payload = """
        {
          "card0": {
            "Card SKU": "AMD Radeon RX 7900 XTX",
            "VRAM Total Memory (B)": "25769803776"
          }
        }
        """.strip()
        with mock.patch("infergrade.environment._run_command", return_value=payload):
            gpu = _detect_amd_gpu()
        self.assertEqual(gpu["hardware_class"], "amd_gpu")
        self.assertEqual(gpu["accelerator_api"], "rocm")
        self.assertEqual(gpu["accelerator_vendor"], "amd")
        self.assertEqual(gpu["accelerator_model"], "AMD Radeon RX 7900 XTX")
        self.assertEqual(gpu["accelerator_vram_gb"], 24.0)

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
        self.assertEqual(gpu["hardware_class"], "apple_silicon")
        self.assertEqual(gpu["memory_architecture"], "unified_memory")
        self.assertEqual(gpu["accelerator_api"], "metal")

    def test_apple_silicon_fallback_uses_native_host_signal_under_rosetta(self):
        def command(command):
            values = {
                ("sysctl", "-n", "hw.optional.arm64"): "1",
                ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M1 Pro",
                ("sysctl", "-n", "hw.model"): "MacBookPro18,3",
                ("sysctl", "-n", "hw.memsize"): str(16 * 1024 ** 3),
            }
            return values.get(tuple(command))

        with mock.patch("infergrade.environment.platform.system", return_value="Darwin"):
            with mock.patch("infergrade.environment.platform.machine", return_value="x86_64"):
                with mock.patch("infergrade.environment._run_command", side_effect=command):
                    gpu = _detect_apple_silicon_fallback()

        self.assertEqual(gpu["hardware_class"], "apple_silicon")
        self.assertEqual(gpu["accelerator_model"], "Apple M1 Pro")
        self.assertEqual(gpu["machine_model"], "MacBookPro18,3")
        self.assertEqual(gpu["accelerator_vram_gb"], 16.0)

    def test_cpu_architecture_and_translation_report_host_and_process_separately(self):
        def command(command):
            if command[-1] == "hw.optional.arm64":
                return "1"
            if command[-1] == "sysctl.proc_translated":
                return "1"
            return None

        with mock.patch("infergrade.environment.platform.system", return_value="Darwin"):
            with mock.patch("infergrade.environment.platform.machine", return_value="x86_64"):
                with mock.patch("infergrade.environment._run_command", side_effect=command):
                    self.assertEqual(_detect_cpu_architecture(), "arm64")
                    self.assertEqual(_detect_process_translation(), "rosetta_2")

    def test_process_translation_does_not_fragment_hardware_identity(self):
        common_patches = (
            mock.patch("infergrade.environment._detect_nvidia_gpu", return_value=None),
            mock.patch("infergrade.environment._detect_amd_gpu", return_value=None),
            mock.patch("infergrade.environment._detect_apple_silicon_gpu", return_value=None),
            mock.patch("infergrade.environment._detect_cpu_model", return_value="Test CPU"),
            mock.patch("infergrade.environment._detect_cpu_architecture", return_value="arm64"),
            mock.patch("infergrade.environment._detect_memory_gb", return_value=16.0),
            mock.patch("infergrade.environment._detect_machine_model", return_value="MacBookPro18,3"),
            mock.patch("infergrade.environment._run_command", return_value=None),
        )
        for patcher in common_patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        with mock.patch("infergrade.environment.platform.machine", return_value="arm64"):
            with mock.patch("infergrade.environment._detect_process_translation", return_value=None):
                native = capture_environment("local_native")
        with mock.patch("infergrade.environment.platform.machine", return_value="x86_64"):
            with mock.patch("infergrade.environment._detect_process_translation", return_value="rosetta_2"):
                translated = capture_environment("local_native")
        self.assertEqual(native["hardware_id"], translated["hardware_id"])
        self.assertEqual(translated["process_architecture"], "x86_64")
        self.assertEqual(translated["process_translation"], "rosetta_2")

    def _fake_drm(self, root, cards):
        for name, files in cards.items():
            device = os.path.join(root, name, "device")
            os.makedirs(device)
            for filename, value in files.items():
                with open(os.path.join(device, filename), "w", encoding="utf-8") as handle:
                    handle.write(value)

    @mock.patch("infergrade.environment.platform.system", return_value="Linux")
    def test_detect_vulkan_gpu_reports_amd_without_rocm_tools(self, _system):
        with tempfile.TemporaryDirectory() as root:
            self._fake_drm(root, {
                "card0": {"vendor": "0x8086\n", "device": "0x9a49\n", "class": "0x030000\n"},
                "card1": {"vendor": "0x1002\n", "device": "0x744c\n", "class": "0x030000\n",
                          "product_name": "AMD Radeon RX 7900 XTX\n", "mem_info_vram_total": "25753026560\n"},
                "card1-DP-1": {},
            })
            gpu = _detect_vulkan_gpu(root)
        self.assertEqual(gpu["accelerator_vendor"], "amd")
        self.assertEqual(gpu["accelerator_api"], "vulkan")
        self.assertEqual(gpu["accelerator_model"], "AMD Radeon RX 7900 XTX")
        self.assertEqual(gpu["accelerator_vram_gb"], 23.98)
        self.assertEqual(gpu["hardware_class"], "amd_gpu")

    @mock.patch("infergrade.environment.platform.system", return_value="Linux")
    def test_detect_vulkan_gpu_keeps_integrated_intel_on_cpu(self, _system):
        with tempfile.TemporaryDirectory() as root:
            self._fake_drm(root, {"card0": {"vendor": "0x8086\n", "device": "0x9a49\n", "class": "0x030000\n"}})
            self.assertIsNone(_detect_vulkan_gpu(root))
        with tempfile.TemporaryDirectory() as root:
            self._fake_drm(root, {"card0": {"vendor": "0x8086\n", "device": "0xe20b\n", "class": "0x030000\n"}})
            gpu = _detect_vulkan_gpu(root)
        self.assertEqual((gpu["accelerator_vendor"], gpu["hardware_class"]), ("intel", "intel_gpu"))

    @mock.patch("infergrade.environment.platform.system", return_value="Windows")
    @mock.patch("infergrade.environment._run_command", return_value="Intel(R) UHD Graphics 770\nAMD Radeon RX 7800 XT")
    def test_detect_vulkan_gpu_reads_windows_adapter_names(self, _run, _system):
        gpu = _detect_vulkan_gpu()
        self.assertEqual(gpu["accelerator_model"], "AMD Radeon RX 7800 XT")
        self.assertEqual(gpu["accelerator_api"], "vulkan")

    def test_vulkan_gpu_is_reported_only_when_native_runs_can_use_it(self):
        radeon = {"accelerator_type": "gpu", "accelerator_vendor": "amd", "accelerator_model": "AMD Radeon RX 7900 XTX",
                  "accelerator_vram_gb": 24.0, "accelerator_count": 1, "hardware_class": "amd_gpu",
                  "memory_architecture": "discrete_vram", "accelerator_api": "vulkan"}
        cases = [
            ("local_native", {}, {"accelerator": "vulkan"}, "amd_gpu"),
            ("local_native", {}, None, "amd_gpu"),
            ("local_native", {}, {"accelerator": "cpu"}, "cpu_only"),
            ("local_native", {"INFERGRADE_ACCELERATOR": "cpu"}, None, "cpu_only"),
            ("local_container", {}, None, "cpu_only"),
        ]
        for mode, env, selection, expected in cases:
            with self.subTest(mode=mode, env=env, selection=selection), \
                    mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch("infergrade.environment._detect_nvidia_gpu", return_value=None), \
                    mock.patch("infergrade.environment._detect_amd_gpu", return_value=None), \
                    mock.patch("infergrade.environment._detect_apple_silicon_gpu", return_value=None), \
                    mock.patch("infergrade.environment._detect_vulkan_gpu", return_value=dict(radeon)), \
                    mock.patch("infergrade.runtimes.selected_llama_cpp_runtime", return_value=selection):
                payload = capture_environment(mode)
            self.assertEqual(payload["hardware_class"], expected)
            if expected == "cpu_only":
                self.assertNotEqual(payload["accelerator_api"], "vulkan")

    @mock.patch("infergrade.environment.platform.system", return_value="Linux")
    def test_detect_vulkan_gpu_counts_cards_without_product_names(self, _system):
        with tempfile.TemporaryDirectory() as root:
            self._fake_drm(root, {
                "card0": {"vendor": "0x1002\n", "device": "0x73bf\n", "class": "0x030000\n"},
                "card1": {"vendor": "0x1002\n", "device": "0x73bf\n", "class": "0x030000\n"},
            })
            gpu = _detect_vulkan_gpu(root)
        self.assertEqual((gpu["accelerator_count"], gpu["accelerator_model"]), (2, "AMD GPU"))

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
        self.assertEqual(payload["hardware_class"], "nvidia_gpu")
        self.assertEqual(payload["accelerator_api"], "cuda")
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
                        "hardware_class": "apple_silicon",
                        "memory_architecture": "unified_memory",
                        "accelerator_api": "metal",
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
        self.assertEqual(payload["hardware_class"], "apple_silicon")
        self.assertEqual(payload["memory_architecture"], "unified_memory")
        self.assertEqual(payload["environment_class"], "local_workstation")

    def test_capture_environment_defaults_to_cpu_only_when_no_accelerator_detected(self):
        with mock.patch("infergrade.environment._detect_nvidia_gpu", return_value=None):
            with mock.patch("infergrade.environment._detect_amd_gpu", return_value=None):
                with mock.patch("infergrade.environment._detect_apple_silicon_gpu", return_value=None), \
                        mock.patch("infergrade.environment._detect_vulkan_gpu", return_value=None):
                    with mock.patch("infergrade.environment._detect_cpu_model", return_value="AMD Ryzen 9 7950X"):
                        with mock.patch("infergrade.environment._detect_memory_gb", return_value=128.0):
                            payload = capture_environment("local_container")
        self.assertEqual(payload["accelerator_type"], "cpu")
        self.assertEqual(payload["hardware_class"], "cpu_only")
        self.assertEqual(payload["memory_architecture"], "system_memory")
        self.assertEqual(payload["cpu_model"], "AMD Ryzen 9 7950X")





class WindowsRegistryModelTests(unittest.TestCase):
    def registry(self, value='AMD EPYC 9V45', kind=1):
        registry = mock.MagicMock()
        registry.HKEY_LOCAL_MACHINE = 1
        registry.KEY_QUERY_VALUE = 2
        registry.KEY_WOW64_64KEY = 256
        registry.REG_SZ = 1
        registry.QueryValueEx.return_value = (value, kind)
        return registry

    def test_queries_only_fixed_model_fields_with_read_only_access(self):
        registry = self.registry()
        with mock.patch.dict(sys.modules, {'winreg': registry}):
            self.assertEqual(_windows_registry_model('cpu'), 'AMD EPYC 9V45')
            _windows_registry_model('machine')
            with self.assertRaises(ValueError):
                _windows_registry_model('serial')
        self.assertEqual(registry.OpenKey.call_count, 2)
        for call in registry.OpenKey.call_args_list:
            self.assertEqual(call.args[-1], 258)
            self.assertEqual(call.args[0], 1)
        self.assertEqual([call.args[1] for call in registry.QueryValueEx.call_args_list],
                         ['ProcessorNameString', 'SystemProductName'])
        registry.SetValueEx.assert_not_called()
        registry.CreateKey.assert_not_called()

    def test_missing_denied_placeholder_controls_and_wrong_types_are_unknown(self):
        for value, kind in [('unknown', 1), ('Bad\x01Name', 1), ('x' * 257, 1), (['machine'], 7), ('Model', 2)]:
            registry = self.registry(value, kind)
            with mock.patch.dict(sys.modules, {'winreg': registry}):
                self.assertIsNone(_windows_registry_model('machine'))
        registry = self.registry()
        registry.OpenKey.side_effect = PermissionError('private registry failure')
        with mock.patch.dict(sys.modules, {'winreg': registry}):
            self.assertIsNone(_windows_registry_model('cpu'))
        with mock.patch.dict(sys.modules, {'winreg': None}):
            self.assertIsNone(_windows_registry_model('cpu'))

    def test_detectors_use_reported_registry_names_without_launching_cim(self):
        with mock.patch('infergrade.environment.platform.system', return_value='Windows'), \
             mock.patch('infergrade.environment._windows_registry_model', side_effect=['AMD EPYC 9V45', 'Virtual Machine']), \
             mock.patch('infergrade.environment._windows_model', side_effect=AssertionError('no PowerShell')):
            self.assertEqual(_detect_cpu_model(), 'AMD EPYC 9V45')
            self.assertEqual(_detect_machine_model(), 'Virtual Machine')

    def test_platform_gate_rejects_windows_architecture_fallback_with_present_machine(self):
        import contextlib
        import io
        import runpy
        from pathlib import Path
        script = Path(__file__).resolve().parents[3] / 'scripts/check_platform_hardware_identity.py'
        output = io.StringIO()
        with mock.patch('infergrade.environment._detect_cpu_model', return_value='AMD64 Family 25 Model 1 Stepping 1, AuthenticAMD'), \
             mock.patch('infergrade.environment._detect_machine_model', return_value='Virtual Machine'), \
             mock.patch('infergrade.environment._windows_model_probe', return_value={'status': 'available', 'value': 'diagnostic name'}), \
             mock.patch('platform.system', return_value='Windows'), \
             mock.patch('platform.machine', return_value='AMD64'), contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(SystemExit, 'unavailable'):
                runpy.run_path(str(script), run_name='__main__')
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(rows[0]['identity_available'])
        self.assertTrue(rows[1]['diagnostic_only'])

    def test_missing_registry_falls_back_to_bounded_cim_and_preserves_unknown(self):
        with mock.patch('infergrade.environment.platform.system', return_value='Windows'), \
             mock.patch('infergrade.environment._windows_registry_model', return_value=None), \
             mock.patch('infergrade.environment.subprocess.run', side_effect=TimeoutError) as run:
            # Exercise the existing subprocess timeout path, not a synthetic brand.
            import subprocess
            run.side_effect = subprocess.TimeoutExpired('probe', 5)
            self.assertIsNone(_detect_machine_model())
        self.assertEqual(run.call_args.kwargs['timeout'], 5)


class MultiGpuInventoryTests(unittest.TestCase):
    def test_dual_4090_inventory_keeps_total_and_largest_card_distinct(self):
        with mock.patch('infergrade.environment._run_command', side_effect=[
            'RTX 4090, 24576, 580.178.04\nRTX 4090, 24576, 580.178.04', None
        ]):
            gpu = _detect_nvidia_gpu()
        self.assertEqual(gpu['accelerator_count'], 2)
        self.assertEqual(gpu['accelerator_vram_gb'], 24)
        self.assertEqual(gpu['accelerator_vram_total_gb'], 48)
        self.assertEqual([device['vram_gb'] for device in gpu['accelerator_devices']], [24, 24])

    def test_mixed_cards_sum_observed_capacity(self):
        with mock.patch('infergrade.environment._run_command', side_effect=[
            'RTX 4090, 24576, 580\nRTX 3060, 12288, 580', None
        ]):
            gpu = _detect_nvidia_gpu()
        self.assertEqual(gpu['accelerator_vram_total_gb'], 36)
        self.assertEqual(gpu['accelerator_vram_gb'], 24)

    def test_missing_card_memory_does_not_invent_total(self):
        with mock.patch('infergrade.environment._run_command', side_effect=[
            'RTX 4090, 24576, 580\nRTX 4090, N/A, 580', None
        ]):
            gpu = _detect_nvidia_gpu()
        self.assertIsNone(gpu['accelerator_vram_total_gb'])


if __name__ == "__main__":
    unittest.main()
