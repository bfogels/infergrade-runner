import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.runtimes import (
    LLAMA_CPP_RUNTIME_ID,
    WINDOWS_CUDA_RUNTIME_ID,
    install_llama_cpp_runtime,
    known_llama_cpp_runtimes,
    runtime_binary_fingerprint,
    runtime_manifest,
    select_llama_cpp_runtime,
    selected_llama_cpp_runtime,
)


class RuntimeManagementTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-runtime-test-")
        self.env_patch = mock.patch.dict(os.environ, {"INFERGRADE_RUNTIME_CACHE_DIR": self.tempdir.name})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tempdir.cleanup()

    def test_runtime_manifest_lists_known_good_llama_cpp_runtime(self):
        manifest = runtime_manifest()
        self.assertEqual(manifest["runtime_family"], "llama.cpp")
        self.assertTrue(manifest["runtimes"])
        self.assertEqual(manifest["runtimes"][0]["source"], "homebrew")

    def test_runtime_manifest_lists_windows_cuda_preview_without_managed_download(self):
        runtimes = {item["runtime_id"]: item for item in known_llama_cpp_runtimes()}
        preview = runtimes["llama-cpp-windows-cuda-cli-preview-2026-05"]
        candidate = preview["candidate_manifest"]

        self.assertEqual(preview["source"], "user_selected")
        self.assertEqual(preview["binary_set"], "llama_cpp_windows_cuda_x86_64")
        self.assertEqual(preview["support_tier"], "preview")
        self.assertEqual(preview["install_command"], [])
        self.assertIsNone(preview["checksum"])
        self.assertEqual(candidate["status"], "candidate_pinned_not_validated")
        self.assertEqual(candidate["upstream"]["tag"], "b10217")
        self.assertEqual(candidate["platform"]["cuda_runtime"], "12.4")
        self.assertEqual(candidate["artifacts"][0]["role"], "llama_cpp_binaries")
        self.assertEqual(
            candidate["artifacts"][0]["sha256"],
            "dd9d505fdf527b0fbad9683581a2af59dda2782a51a346a9d391b9256b4a2af5",
        )
        self.assertEqual(candidate["artifacts"][1]["role"], "cuda_runtime_dlls")
        self.assertFalse(candidate["managed_download_enabled"])
        self.assertIn("run_known_good_gguf", candidate["validation_required"])
        self.assertEqual(candidate["review"]["status"], "blocked")
        review_checks = {item["id"]: item for item in candidate["review"]["checks"]}
        self.assertEqual(review_checks["asset_sha256_digests_pinned"]["status"], "recorded")
        self.assertEqual(review_checks["archive_contents_inspected"]["status"], "passed")
        self.assertEqual(review_checks["license_and_runtime_dll_distribution_reviewed"]["status"], "pending")
        self.assertEqual(review_checks["secret_free_support_export_captured"]["status"], "pending")
        self.assertIn("managed download remains disabled", " ".join(preview["notes"]))

    def test_install_runtime_without_execute_returns_plan_only(self):
        plan = install_llama_cpp_runtime(runtime_id=LLAMA_CPP_RUNTIME_ID, execute=False)
        self.assertEqual(plan["action"], "plan")
        self.assertIn("install_command", plan["runtime"])
        self.assertIsNone(selected_llama_cpp_runtime())

    @mock.patch("infergrade.runtimes.shutil.which")
    def test_select_existing_runtime_writes_managed_selection(self, which_mock):
        which_mock.side_effect = lambda name: name if name in ("/custom/llama-cli", "/custom/llama-server") else None
        selection = select_llama_cpp_runtime(
            runtime_id=LLAMA_CPP_RUNTIME_ID,
            cli_path="/custom/llama-cli",
            server_path="/custom/llama-server",
        )
        self.assertEqual(selection["source"], "homebrew")
        self.assertEqual(selection["binaries"]["cli"], "/custom/llama-cli")
        self.assertEqual(selected_llama_cpp_runtime()["binaries"]["server"], "/custom/llama-server")

    @mock.patch("infergrade.runtimes.shutil.which")
    def test_select_existing_runtime_keeps_path_fallback_for_non_cuda_server(self, which_mock):
        which_mock.side_effect = lambda name: {
            "/custom/llama-cli": "/custom/llama-cli",
            "llama-server": "/usr/local/bin/llama-server",
            "llama-perplexity": "/usr/local/bin/llama-perplexity",
        }.get(name)

        selection = select_llama_cpp_runtime(runtime_id=LLAMA_CPP_RUNTIME_ID, cli_path="/custom/llama-cli")

        self.assertEqual(selection["source"], "homebrew")
        self.assertEqual(selection["binaries"]["server"], "/usr/local/bin/llama-server")
        self.assertEqual(selection["binaries"]["perplexity"], "/usr/local/bin/llama-perplexity")

    def test_unlabeled_explicit_runtime_uses_cli_fingerprint_identity(self):
        paths = {}
        for name in ("llama-cli", "llama-server", "llama-perplexity"):
            path = os.path.join(self.tempdir.name, name)
            with open(path, "wb") as handle:
                handle.write((name + " local runtime").encode("utf-8"))
            os.chmod(path, 0o755)
            paths[name] = path

        selection = select_llama_cpp_runtime(cli_path=paths["llama-cli"])
        expected_sha256 = hashlib.sha256(b"llama-cli local runtime").hexdigest()

        self.assertEqual(selection["runtime_id"], "llama-cpp-local-%s" % expected_sha256)
        self.assertEqual(selection["runtime_identity_basis"], "cli_sha256")
        self.assertEqual(selection["source"], "selected_existing")
        self.assertEqual(selection["channel"], "local_binary")
        self.assertNotEqual(selection["runtime_id"], LLAMA_CPP_RUNTIME_ID)
        self.assertNotIn("checksum", selection)
        self.assertNotIn("notes", selection)
        self.assertEqual(selected_llama_cpp_runtime()["runtime_id"], selection["runtime_id"])

    @mock.patch("infergrade.runtimes.shutil.which")
    def test_select_existing_runtime_rejects_bad_explicit_server_without_path_fallback(self, which_mock):
        which_mock.side_effect = lambda name: {
            "/custom/llama-cli": "/custom/llama-cli",
            "llama-server": "/usr/local/bin/llama-server",
        }.get(name)

        with self.assertRaisesRegex(RuntimeError, "server"):
            select_llama_cpp_runtime(
                cli_path="/custom/llama-cli",
                server_path="/missing/llama-server",
            )

    @mock.patch("infergrade.runtimes.shutil.which")
    def test_select_windows_cuda_preview_records_support_boundary(self, which_mock):
        known_paths = {
            "/cuda/llama-cli.exe",
            "/cuda/llama-server.exe",
            "/cuda/llama-perplexity.exe",
        }
        which_mock.side_effect = lambda name: name if name in known_paths else None

        selection = select_llama_cpp_runtime(
            runtime_id=WINDOWS_CUDA_RUNTIME_ID,
            cli_path="/cuda/llama-cli.exe",
        )

        self.assertEqual(selection["binary_set"], "llama_cpp_windows_cuda_x86_64")
        self.assertEqual(selection["support_tier"], "preview")
        self.assertFalse(selection["checksum_verified"])
        self.assertEqual(selection["checksum_status"], "user_selected_unverified")
        self.assertIn("full Hub loop", selection["claim_boundary"])
        self.assertIn("preview-only", selection["selection_warning"])
        self.assertEqual(selection["binaries"]["server"], "/cuda/llama-server.exe")
        self.assertEqual(selected_llama_cpp_runtime()["binaries"]["perplexity"], "/cuda/llama-perplexity.exe")

    def test_runtime_binary_fingerprint_records_bounded_sha256(self):
        path = os.path.join(self.tempdir.name, "llama-cli.exe")
        with open(path, "wb") as handle:
            handle.write(b"llama runtime")

        fingerprint = runtime_binary_fingerprint(path)

        self.assertEqual(fingerprint["status"], "recorded")
        self.assertEqual(fingerprint["size_bytes"], len(b"llama runtime"))
        self.assertEqual(fingerprint["sha256"], hashlib.sha256(b"llama runtime").hexdigest())

    def test_select_windows_cuda_preview_records_binary_fingerprints(self):
        for name in ("llama-cli.exe", "llama-server.exe", "llama-perplexity.exe"):
            path = os.path.join(self.tempdir.name, name)
            with open(path, "wb") as handle:
                handle.write(name.encode("utf-8"))
            os.chmod(path, 0o755)

        selection = select_llama_cpp_runtime(
            runtime_id=WINDOWS_CUDA_RUNTIME_ID,
            cli_path=os.path.join(self.tempdir.name, "llama-cli.exe"),
        )

        cli_fingerprint = selection["binary_fingerprints"]["cli"]
        self.assertEqual(cli_fingerprint["status"], "recorded")
        self.assertEqual(cli_fingerprint["sha256"], hashlib.sha256(b"llama-cli.exe").hexdigest())
        self.assertEqual(selected_llama_cpp_runtime()["binary_fingerprints"]["server"]["status"], "recorded")

    @mock.patch("infergrade.runtimes.shutil.which")
    def test_select_windows_cuda_preview_requires_perplexity_sibling(self, which_mock):
        known_paths = {
            "/cuda/llama-cli.exe",
            "/cuda/llama-server.exe",
        }
        which_mock.side_effect = lambda name: name if name in known_paths else None

        with self.assertRaisesRegex(RuntimeError, "perplexity"):
            select_llama_cpp_runtime(
                runtime_id=WINDOWS_CUDA_RUNTIME_ID,
                cli_path="/cuda/llama-cli.exe",
            )


if __name__ == "__main__":
    unittest.main()


class NativeManagedBridgeTests(unittest.TestCase):
    @mock.patch("infergrade.runtimes._native_runtime_command")
    def test_default_install_delegates_to_native_authority(self, command):
        command.return_value = {"selection": {"runtime_build": {"runtime_build_id": "exact"}}}
        result = install_llama_cpp_runtime(execute=True)
        command.assert_called_once_with(["install"])
        self.assertEqual(result["selected"]["runtime_build"]["runtime_build_id"], "exact")

    @mock.patch("infergrade.runtimes.shutil.which", return_value=None)
    def test_missing_native_cli_explains_desktop_recovery(self, command):
        with self.assertRaisesRegex(RuntimeError, "Make runtime ready"):
            install_llama_cpp_runtime(execute=True)


class ListenerRuntimeSetupTests(unittest.TestCase):
    def setUp(self):
        from infergrade.runtimes import prepare_native_listener_runtime
        self.prepare = prepare_native_listener_runtime

    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch('infergrade.runtimes.install_llama_cpp_runtime')
    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value=None)
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path')
    @mock.patch('infergrade.runtimes.shutil.which', return_value=None)
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_first_start_installs_and_verifies_both_binaries(self, which, managed, selected, install, run):
        managed.side_effect = [None, None, '/managed/llama-cli', '/managed/llama-server']
        run.return_value = mock.Mock(returncode=0)
        self.prepare()
        install.assert_called_once_with(execute=True)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [['/managed/llama-cli', '--version'], ['/managed/llama-server', '--version']])

    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch('infergrade.runtimes.install_llama_cpp_runtime')
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_existing_build_is_verified_without_upgrade(self, managed, install, run):
        run.return_value = mock.Mock(returncode=0)
        self.prepare()
        install.assert_not_called()

    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_loader_error_survives_setup_failure(self, managed, run):
        run.return_value = mock.Mock(returncode=1, stderr='GLIBC_2.38 not found', stdout='')
        with self.assertRaisesRegex(RuntimeError, 'GLIBC_2.38 not found'):
            self.prepare()

    @mock.patch('infergrade.runtimes.install_llama_cpp_runtime')
    @mock.patch('infergrade.runtimes.shutil.which', return_value=None)
    @mock.patch.dict(os.environ, {'INFERGRADE_LLAMA_CPP_CLI': '/missing/cli'}, clear=True)
    def test_broken_explicit_runtime_is_not_replaced(self, which, install):
        with self.assertRaisesRegex(RuntimeError, 'configured llama-cli'):
            self.prepare()
        install.assert_not_called()

    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch('infergrade.runtimes.install_llama_cpp_runtime')
    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value=None)
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch('infergrade.runtimes.shutil.which', return_value='/system/llama')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_installer_prefers_managed_default_to_unselected_system_binaries(self, which, managed, selected, install, run):
        run.return_value = mock.Mock(returncode=0)
        self.prepare(prefer_managed=True)
        install.assert_called_once_with(execute=True)
        self.assertEqual([call.args[0][0] for call in run.call_args_list], ['/managed/cli', '/managed/server'])

    @mock.patch('infergrade.runtimes.install_llama_cpp_runtime')
    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value={'runtime_id': 'selected-build'})
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', return_value=None)
    @mock.patch('infergrade.runtimes.shutil.which', return_value='/system/llama')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_missing_selection_is_not_masked_by_system_binaries(self, which, managed, selected, install):
        with self.assertRaisesRegex(RuntimeError, 'selected llama.cpp runtime is incomplete'):
            self.prepare(prefer_managed=True)
        install.assert_not_called()

    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value={'accelerator': 'cuda'})
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_cuda_listener_requires_a_device_from_the_actual_managed_runtime(self, run, managed, selected):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0),
                           mock.Mock(returncode=0, stdout='Available devices:\n  (none)\n', stderr='driver initialization failed')]
        with self.assertRaisesRegex(RuntimeError, 'usable NVIDIA device.*driver initialization failed'):
            self.prepare()
        self.assertEqual(run.call_args_list[-1].args[0], ['/managed/cli', '--verbose', '--list-devices'])

    @mock.patch('infergrade.runtimes.platform.system', return_value='Linux')
    @mock.patch('infergrade.runtimes.Path.is_file', return_value=True)
    @mock.patch('infergrade.runtimes.shutil.which', return_value='/usr/bin/ldd')
    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value={'accelerator': 'cuda'})
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_missing_nccl_is_reported_as_a_loader_failure(self, run, managed, selected, which, is_file, system):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0),
                           mock.Mock(returncode=0, stdout='Available devices:\n  (none)\n', stderr=''),
                           mock.Mock(returncode=0, stdout='libnccl.so.2 => not found\n', stderr='')]
        with self.assertRaisesRegex(RuntimeError, 'backend could not load.*libnccl.so.2'):
            self.prepare()
        self.assertEqual(run.call_args_list[-1].args[0], ['ldd', '/managed/libggml-cuda.so'])

    @mock.patch('infergrade.runtimes.platform.system', return_value='Linux')
    @mock.patch('infergrade.runtimes.Path.is_file', return_value=True)
    @mock.patch('infergrade.runtimes.shutil.which', return_value='/usr/bin/ldd')
    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value={'accelerator': 'cuda'})
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_absent_host_driver_is_not_a_missing_redistributable(self, run, managed, selected, which, is_file, system):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0),
                           mock.Mock(returncode=0, stdout='Available devices:\n  (none)\n', stderr=''),
                           mock.Mock(returncode=0, stdout='libcuda.so.1 => not found\n', stderr='')]
        with self.assertRaisesRegex(RuntimeError, 'usable NVIDIA device.*Host NVIDIA driver library libcuda.so.1 is unavailable'):
            self.prepare()

    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value={'accelerator': 'cuda'})
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_cuda_listener_accepts_two_observed_runtime_devices(self, run, managed, selected):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0),
                           mock.Mock(returncode=0, stdout='Available devices:\n  CUDA0: NVIDIA RTX 4090\n  CUDA1: NVIDIA RTX 4090\n', stderr='')]
        self.prepare()


    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value={'accelerator': 'vulkan'})
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_vulkan_listener_refuses_cpu_only_execution(self, run, managed, selected):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0),
                           mock.Mock(returncode=0, stdout='Available devices:\n', stderr='ggml_vulkan: No devices found.')]
        with self.assertRaisesRegex(RuntimeError, 'no usable AMD/Intel GPU.*INFERGRADE_ACCELERATOR=cpu.*No devices found'):
            self.prepare()
        self.assertEqual(run.call_args_list[-1].args[0], ['/managed/cli', '--list-devices'])

    @mock.patch('infergrade.runtimes.selected_llama_cpp_runtime', return_value={'accelerator': 'vulkan'})
    @mock.patch('infergrade.runtimes.managed_llama_cpp_binary_path', side_effect=['/managed/cli', '/managed/server'])
    @mock.patch('infergrade.runtimes.subprocess.run')
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_vulkan_listener_accepts_an_observed_radeon_device(self, run, managed, selected):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0),
                           mock.Mock(returncode=0, stdout='Available devices:\n  Vulkan0: AMD Radeon RX 7900 XTX (RADV NAVI31) (24560 MiB, 24000 MiB free)\n', stderr='')]
        self.prepare()
