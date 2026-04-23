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
    canonicalize_hf_artifact_reference,
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

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_remote_artifact_resolution_expands_user_cache_dir(self, urlopen_mock):
        payload = b"remote-gguf"
        response_handle = tempfile.NamedTemporaryFile(delete=False)
        response_handle.write(payload)
        response_handle.close()
        urlopen_mock.return_value = open(response_handle.name, "rb")
        home_dir = os.path.join(self.tempdir.name, "home")
        os.makedirs(home_dir, exist_ok=True)
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
            quant_artifact_cache_dir="~/.cache/infergrade/artifacts",
        )
        try:
            with mock.patch.dict(os.environ, {"HOME": home_dir}, clear=False):
                resolved = resolve_quant_artifact(request)
        finally:
            os.unlink(response_handle.name)
        self.assertTrue(resolved.resolved_path.startswith(os.path.join(home_dir, ".cache", "infergrade", "artifacts")))

    def test_hf_artifact_urls_expand_to_huggingface_resolve_urls(self):
        self.assertEqual(
            artifact_to_download_url(
                "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
            ),
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        )

    @mock.patch("infergrade.artifacts._fetch_huggingface_siblings")
    def test_canonicalize_hf_artifact_reference_fixes_case_mismatch(self, siblings_mock):
        siblings_mock.return_value = [
            "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
            "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
        ]
        corrected = canonicalize_hf_artifact_reference(
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf"
        )
        self.assertEqual(
            corrected,
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        )

    @mock.patch("infergrade.artifacts.compute_file_sha256", return_value="abc123")
    @mock.patch("infergrade.artifacts._fetch_huggingface_siblings")
    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_remote_artifact_resolution_retries_with_canonical_hf_path_on_404(
        self,
        download_mock,
        siblings_mock,
        _sha_mock,
    ):
        siblings_mock.return_value = ["Qwen2.5-7B-Instruct-Q4_K_M.gguf"]

        def side_effect(download_url, destination_path):
            if "qwen2.5-7b-instruct-q4_k_m.gguf" in download_url:
                raise RuntimeError("curl failed while downloading %s: 404" % download_url)
            with open(destination_path, "wb") as handle:
                handle.write(b"canonical-download")

        download_mock.side_effect = side_effect
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
            quant_artifact_cache_dir=self.cache_dir,
        )
        resolved = resolve_quant_artifact(request)
        self.assertEqual(
            resolved.original_uri,
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        )
        self.assertIn("Qwen2.5-7B-Instruct-Q4_K_M.gguf", resolved.download_url)

    @mock.patch("infergrade.artifacts.subprocess.run")
    @mock.patch("infergrade.artifacts.shutil.which", return_value="/usr/bin/curl")
    @mock.patch("infergrade.artifacts.urllib_request.urlopen", side_effect=urllib_error.URLError("ssl"))
    def test_remote_artifact_resolution_falls_back_to_curl(self, _urlopen_mock, _which_mock, run_mock):
        def fake_run(command, capture_output, text):
            destination_path = command[command.index("-o") + 1]
            # Verify the hardened curl invocation pins protocols to https so
            # a 30x redirect cannot downgrade the transfer to cleartext.
            self.assertEqual(command[command.index("--proto") + 1], "=https")
            self.assertEqual(command[command.index("--proto-redir") + 1], "=https")
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


class ArtifactSecurityHardeningTests(unittest.TestCase):
    """Cover the security-review hardening around hub-controlled run configs."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-artifacts-sec-")
        self.cache_dir = os.path.join(self.tempdir.name, "cache")

    def tearDown(self):
        self.tempdir.cleanup()

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_traversal_filename_is_rejected(self, urlopen_mock):
        # If a malicious hub supplies ../../../etc/passwd as the filename,
        # the runner must not write downloaded bytes outside the cache dir.
        urlopen_mock.return_value = mock.MagicMock()  # should never be called
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
            quant_artifact_cache_dir=self.cache_dir,
            quant_artifact_filename="../../../../../etc/passwd",
        )
        with self.assertRaises(ValueError) as caught:
            resolve_quant_artifact(request)
        self.assertIn("quant_artifact_filename", str(caught.exception))
        urlopen_mock.assert_not_called()

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_windows_separator_filename_is_rejected(self, urlopen_mock):
        urlopen_mock.return_value = mock.MagicMock()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
            quant_artifact_cache_dir=self.cache_dir,
            quant_artifact_filename="..\\..\\Windows\\System32\\drivers\\etc\\hosts",
        )
        with self.assertRaises(ValueError):
            resolve_quant_artifact(request)
        urlopen_mock.assert_not_called()

    def test_plain_filename_is_preserved(self):
        # Positive control: a clean filename still flows through to disk.
        with mock.patch("infergrade.artifacts.urllib_request.urlopen") as urlopen_mock:
            payload = b"clean-gguf"
            handle = tempfile.NamedTemporaryFile(delete=False)
            handle.write(payload)
            handle.close()
            urlopen_mock.return_value = open(handle.name, "rb")
            request = RunRequest(
                model="Qwen/Qwen2.5-7B-Instruct",
                backend="llama.cpp",
                tier="canary",
                quant_artifact="hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
                quant_artifact_cache_dir=self.cache_dir,
                quant_artifact_filename="qwen2.5-7b-instruct-q4_k_m.gguf",
            )
            try:
                resolved = resolve_quant_artifact(request)
            finally:
                os.unlink(handle.name)
            self.assertTrue(resolved.resolved_path.startswith(self.cache_dir))
            self.assertTrue(resolved.resolved_path.endswith("qwen2.5-7b-instruct-q4_k_m.gguf"))

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_cleartext_http_artifact_without_sha_is_rejected(self, urlopen_mock):
        # MITM on unpinned http:// downloads is the exact scenario we close.
        urlopen_mock.return_value = mock.MagicMock()
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="http://example.com/model.gguf",
            quant_artifact_cache_dir=self.cache_dir,
        )
        with self.assertRaises(ValueError) as caught:
            resolve_quant_artifact(request)
        self.assertIn("http://", str(caught.exception))
        urlopen_mock.assert_not_called()

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_cleartext_http_artifact_with_pinned_sha_is_allowed(self, urlopen_mock):
        # A pinned SHA256 is a sufficient integrity check even over cleartext.
        payload = b"pinned-gguf-bytes"
        expected_sha = hashlib.sha256(payload).hexdigest()
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(payload)
        handle.close()
        urlopen_mock.return_value = open(handle.name, "rb")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="http://example.com/model.gguf",
            quant_artifact_sha256=expected_sha,
            quant_artifact_cache_dir=self.cache_dir,
        )
        try:
            resolved = resolve_quant_artifact(request)
        finally:
            os.unlink(handle.name)
        self.assertEqual(resolved.sha256, expected_sha)
        self.assertTrue(resolved.resolved_path.startswith(self.cache_dir))


if __name__ == "__main__":
    unittest.main()
