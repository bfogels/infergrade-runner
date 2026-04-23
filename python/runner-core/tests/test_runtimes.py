import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.runtimes import (
    install_llama_cpp_runtime,
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


if __name__ == "__main__":
    unittest.main()
