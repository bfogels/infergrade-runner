import hashlib
import os
import sys
import tempfile
import unittest
from urllib import error as urllib_error
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.artifacts import (
    artifact_to_download_url,
    compute_file_sha256,
    resolve_quant_artifact,
)
from infergrade.models import RunRequest


class ArtifactResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-artifacts-")
        self.cache_dir = os.path.join(self.tempdir.name, "cache")
        self.local_model = os.path.join(self.tempdir.name, "model.gguf")
        with open(self.local_model, "wb") as handle:
            handle.write(b"gguf-test-payload")
        self.local_sha = hashlib.sha256(b"gguf-test-payload").hexdigest()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_local_artifact_resolution_verifies_sha(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=self.local_model,
            quant_artifact_sha256=self.local_sha,
        )
        resolved = resolve_quant_artifact(request)
        self.assertEqual(resolved.resolved_path, os.path.abspath(self.local_model))
        self.assertEqual(resolved.sha256, self.local_sha)
        self.assertFalse(resolved.cache_hit)

    def test_local_artifact_resolution_rejects_sha_mismatch(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=self.local_model,
            quant_artifact_sha256="deadbeef",
        )
        with self.assertRaises(ValueError):
            resolve_quant_artifact(request)

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_remote_artifact_resolution_downloads_to_cache(self, urlopen_mock):
        payload = b"remote-gguf"
        response_handle = tempfile.NamedTemporaryFile(delete=False)
        response_handle.write(payload)
        response_handle.close()
        urlopen_mock.return_value = open(response_handle.name, "rb")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
            quant_artifact_cache_dir=self.cache_dir,
        )
        try:
            resolved = resolve_quant_artifact(request)
        finally:
            os.unlink(response_handle.name)
        self.assertFalse(resolved.cache_hit)
        self.assertTrue(os.path.isfile(resolved.resolved_path))
        self.assertEqual(resolved.sha256, compute_file_sha256(resolved.resolved_path))
        self.assertTrue(resolved.resolved_path.startswith(self.cache_dir))

    def test_hf_artifact_urls_expand_to_huggingface_resolve_urls(self):
        self.assertEqual(
            artifact_to_download_url(
                "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf"
            ),
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
        )

    @mock.patch("infergrade.artifacts.subprocess.run")
    @mock.patch("infergrade.artifacts.shutil.which", return_value="/usr/bin/curl")
    @mock.patch("infergrade.artifacts.urllib_request.urlopen", side_effect=urllib_error.URLError("ssl"))
    def test_remote_artifact_resolution_falls_back_to_curl(self, _urlopen_mock, _which_mock, run_mock):
        def fake_run(command, capture_output, text):
            destination_path = command[4]
            with open(destination_path, "wb") as handle:
                handle.write(b"curl-download")
            return mock.Mock(returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            quant_artifact_cache_dir=self.cache_dir,
        )
        resolved = resolve_quant_artifact(request)
        self.assertTrue(os.path.isfile(resolved.resolved_path))
        self.assertEqual(resolved.sha256, compute_file_sha256(resolved.resolved_path))


if __name__ == "__main__":
    unittest.main()
