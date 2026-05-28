import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.runtimes import (
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

        self.assertEqual(preview["source"], "user_selected")
        self.assertEqual(preview["binary_set"], "llama_cpp_windows_cuda_x86_64")
        self.assertEqual(preview["support_tier"], "preview")
        self.assertEqual(preview["install_command"], [])
        self.assertIsNone(preview["checksum"])
        self.assertIn("No CUDA binary is downloaded", " ".join(preview["notes"]))

    def test_install_runtime_without_execute_returns_plan_only(self):
        plan = install_llama_cpp_runtime(execute=False)
        self.assertEqual(plan["action"], "plan")
        self.assertIn("install_command", plan["runtime"])
        self.assertIsNone(selected_llama_cpp_runtime())

    @mock.patch("infergrade.runtimes.shutil.which")
    def test_select_existing_runtime_writes_managed_selection(self, which_mock):
        which_mock.side_effect = lambda name: name if name in ("/custom/llama-cli", "/custom/llama-server") else None
        selection = select_llama_cpp_runtime(cli_path="/custom/llama-cli", server_path="/custom/llama-server")
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

        selection = select_llama_cpp_runtime(cli_path="/custom/llama-cli")

        self.assertEqual(selection["source"], "homebrew")
        self.assertEqual(selection["binaries"]["server"], "/usr/local/bin/llama-server")
        self.assertEqual(selection["binaries"]["perplexity"], "/usr/local/bin/llama-perplexity")

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
