import hashlib
import io
import os
import sys
import tempfile
import unittest
from urllib import error as urllib_error
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.artifacts import (
    _download_remote_artifact,
    _download_with_bounded_curl,
    _install_cache_file_without_overwrite,
    artifact_cache_status,
    artifact_to_download_url,
    canonicalize_hf_artifact_reference,
    compute_file_sha256,
    ensure_min_free_space,
    prune_partial_artifacts,
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

    def test_local_artifact_resolution_enforces_authorized_size(self):
        matching = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=self.local_model,
            quant_artifact_download_size_bytes=os.path.getsize(self.local_model),
        )
        self.assertEqual(resolve_quant_artifact(matching).size_bytes, os.path.getsize(self.local_model))
        matching.quant_artifact_download_size_bytes += 1
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            resolve_quant_artifact(matching)

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_remote_artifact_enforces_authorized_size_and_reserves_disk(self, download_mock):
        payload = b"authorized-remote-gguf"

        def write_download(_url, path, expected_size_bytes=None):
            self.assertEqual(expected_size_bytes, len(payload))
            with open(path, "wb") as handle:
                handle.write(payload)

        download_mock.side_effect = write_download
        request = RunRequest(
            model="example/model",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://example/model-GGUF/model.gguf",
            quant_artifact_revision="pinned-commit",
            quant_artifact_sha256=hashlib.sha256(payload).hexdigest(),
            quant_artifact_download_size_bytes=len(payload),
            quant_artifact_cache_dir=self.cache_dir,
        )
        with mock.patch("infergrade.artifacts.min_artifact_cache_free_bytes", return_value=500):
            with mock.patch("infergrade.artifacts.ensure_min_free_space") as free_space_mock:
                resolved = resolve_quant_artifact(request)
        self.assertEqual(resolved.size_bytes, len(payload))
        self.assertEqual(
            free_space_mock.call_args.args[1],
            len(payload) + 500,
        )

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_remote_artifact_rejects_download_smaller_than_authorized_size(self, download_mock):
        def write_short(_url, path, expected_size_bytes=None):
            with open(path, "wb") as handle:
                handle.write(b"short")

        download_mock.side_effect = write_short
        request = RunRequest(
            model="example/model",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://example/model-GGUF/model.gguf",
            quant_artifact_revision="pinned-commit",
            quant_artifact_sha256=hashlib.sha256(b"short").hexdigest(),
            quant_artifact_download_size_bytes=100,
            quant_artifact_cache_dir=self.cache_dir,
        )
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            resolve_quant_artifact(request)
        self.assertFalse(any(name.endswith("model.gguf") for name in os.listdir(self.cache_dir)))

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_remote_transport_rejects_oversize_content_length_before_copy(self, urlopen_mock):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.headers = {"Content-Length": "4"}
        urlopen_mock.return_value = response
        destination = os.path.join(self.tempdir.name, "bounded.tmp")
        with self.assertRaisesRegex(RuntimeError, "size header mismatch"):
            _download_remote_artifact(
                "https://example.test/model.gguf",
                destination,
                expected_size_bytes=3,
            )
        response.read.assert_not_called()

    @mock.patch("infergrade.artifacts.subprocess.Popen")
    def test_curl_fallback_stream_is_bounded_by_runner(self, popen_mock):
        process = mock.MagicMock()
        process.stdin = None
        process.stdout = io.BytesIO(b"four")
        process.stderr = io.BytesIO(b"")
        process.poll.return_value = 0
        popen_mock.return_value = process
        destination = os.path.join(self.tempdir.name, "bounded-curl.tmp")
        with self.assertRaisesRegex(RuntimeError, "exceeded authorized size"):
            _download_with_bounded_curl(
                "https://example.test/model.gguf",
                destination,
                expected_size_bytes=3,
            )
        process.terminate.assert_called_once_with()

    @mock.patch("infergrade.artifacts._install_cache_file_without_overwrite")
    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_concurrent_cache_winner_must_match_authorized_size(self, download_mock, install_mock):
        expected = b"small"

        def write_download(_url, path, expected_size_bytes=None):
            with open(path, "wb") as handle:
                handle.write(expected)

        def publish_larger_winner(tmp_path, cache_path):
            with open(cache_path, "wb") as handle:
                handle.write(b"larger-race-winner")
            return False

        download_mock.side_effect = write_download
        install_mock.side_effect = publish_larger_winner
        request = RunRequest(
            model="example/model",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://example/model-GGUF/model.gguf",
            quant_artifact_revision="pinned-commit",
            quant_artifact_download_size_bytes=len(expected),
            quant_artifact_cache_dir=self.cache_dir,
        )
        with self.assertRaisesRegex(ValueError, "size mismatch"):
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

    @mock.patch("infergrade.artifacts.urllib_request.urlopen")
    def test_remote_artifact_resolution_uses_huggingface_token_env(self, urlopen_mock):
        payload = b"gated-remote-gguf"
        response_handle = tempfile.NamedTemporaryFile(delete=False)
        response_handle.write(payload)
        response_handle.close()
        urlopen_mock.return_value = open(response_handle.name, "rb")
        request = RunRequest(
            model="google/gemma-3-1b-it",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://google/gemma-3-1b-it-qat-q4_0-gguf/gemma-3-1b-it-q4_0.gguf",
            quant_artifact_cache_dir=self.cache_dir,
        )
        try:
            with mock.patch.dict(os.environ, {"HF_TOKEN": "hf_test_token"}, clear=False):
                resolved = resolve_quant_artifact(request)
        finally:
            os.unlink(response_handle.name)

        self.assertTrue(os.path.isfile(resolved.resolved_path))
        request_arg = urlopen_mock.call_args.args[0]
        self.assertEqual(request_arg.get_header("Authorization"), "Bearer hf_test_token")

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
        def fake_run(command, capture_output, text, input=None):
            destination_path = command[command.index("-o") + 1]
            # Verify the hardened curl invocation pins protocols to https so
            # a 30x redirect cannot downgrade the transfer to cleartext.
            self.assertEqual(command[command.index("--proto") + 1], "=https")
            self.assertEqual(command[command.index("--proto-redir") + 1], "=https")
            self.assertIsNone(input)
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

    @mock.patch("infergrade.artifacts.subprocess.run")
    @mock.patch("infergrade.artifacts.shutil.which", return_value="/usr/bin/curl")
    @mock.patch("infergrade.artifacts.urllib_request.urlopen", side_effect=urllib_error.URLError("ssl"))
    def test_remote_artifact_curl_fallback_keeps_hf_token_out_of_argv(self, _urlopen_mock, _which_mock, run_mock):
        def fake_run(command, capture_output, text, input=None):
            joined = " ".join(command)
            self.assertNotIn("hf_secret_token", joined)
            self.assertIn("-K", command)
            self.assertEqual(command[command.index("-K") + 1], "-")
            self.assertIn("Authorization: Bearer hf_secret_token", input or "")
            destination_path = command[command.index("-o") + 1]
            with open(destination_path, "wb") as handle:
                handle.write(b"curl-download")
            return mock.Mock(returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        request = RunRequest(
            model="google/gemma-3-1b-it",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://google/gemma-3-1b-it-qat-q4_0-gguf/gemma-3-1b-it-q4_0.gguf",
            quant_artifact_cache_dir=self.cache_dir,
        )

        with mock.patch.dict(os.environ, {"HF_TOKEN": "hf_secret_token"}, clear=False):
            resolved = resolve_quant_artifact(request)

        self.assertTrue(os.path.isfile(resolved.resolved_path))

    def test_artifact_cache_status_counts_completed_and_partial_files(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        completed_path = os.path.join(self.cache_dir, "abc-model.gguf")
        partial_path = os.path.join(self.cache_dir, "infergrade-artifact-old.tmp")
        with open(completed_path, "wb") as handle:
            handle.write(b"complete")
        with open(partial_path, "wb") as handle:
            handle.write(b"partial-download")

        with mock.patch.dict(os.environ, {"INFERGRADE_MIN_ARTIFACT_CACHE_FREE_GB": "0"}, clear=False):
            status = artifact_cache_status(self.cache_dir)

        self.assertEqual(status["artifact_count"], 1)
        self.assertEqual(status["artifact_bytes"], len(b"complete"))
        self.assertEqual(status["partial_count"], 1)
        self.assertEqual(status["partial_bytes"], len(b"partial-download"))
        self.assertEqual(status["total_count"], 2)

    def test_prune_partial_artifacts_leaves_completed_artifacts(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        completed_path = os.path.join(self.cache_dir, "abc-model.gguf")
        partial_path = os.path.join(self.cache_dir, "infergrade-artifact-old.tmp")
        with open(completed_path, "wb") as handle:
            handle.write(b"complete")
        with open(partial_path, "wb") as handle:
            handle.write(b"partial")
        stale_time = 1000000000
        os.utime(partial_path, (stale_time, stale_time))

        dry_run = prune_partial_artifacts(self.cache_dir, dry_run=True)
        self.assertEqual(dry_run["removed_count"], 1)
        self.assertTrue(os.path.exists(partial_path))

        pruned = prune_partial_artifacts(self.cache_dir)
        self.assertEqual(pruned["removed_count"], 1)
        self.assertTrue(os.path.exists(completed_path))
        self.assertFalse(os.path.exists(partial_path))

    def test_prune_partial_artifacts_skips_fresh_partials_by_default(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        partial_path = os.path.join(self.cache_dir, "infergrade-artifact-active.tmp")
        with open(partial_path, "wb") as handle:
            handle.write(b"active")

        pruned = prune_partial_artifacts(self.cache_dir)

        self.assertEqual(pruned["removed_count"], 0)
        self.assertTrue(os.path.exists(partial_path))

    def test_prune_partial_artifacts_allows_explicit_zero_age(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        partial_path = os.path.join(self.cache_dir, "infergrade-artifact-active.tmp")
        with open(partial_path, "wb") as handle:
            handle.write(b"active")

        pruned = prune_partial_artifacts(self.cache_dir, min_age_seconds=0)

        self.assertEqual(pruned["removed_count"], 1)
        self.assertFalse(os.path.exists(partial_path))

    def test_ensure_min_free_space_raises_before_download(self):
        usage = mock.Mock(free=1024)
        with mock.patch("infergrade.artifacts.shutil.disk_usage", return_value=usage):
            with self.assertRaises(RuntimeError) as caught:
                ensure_min_free_space(self.cache_dir, 2048, "artifact cache")
        self.assertIn("insufficient free disk space", str(caught.exception))

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_remote_artifact_resolution_checks_free_space_before_download(self, download_mock):
        usage = mock.Mock(free=1024)
        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            quant_artifact_cache_dir=self.cache_dir,
        )
        with mock.patch.dict(os.environ, {"INFERGRADE_MIN_ARTIFACT_CACHE_FREE_GB": "1"}, clear=False):
            with mock.patch("infergrade.artifacts.shutil.disk_usage", return_value=usage):
                with self.assertRaises(RuntimeError):
                    resolve_quant_artifact(request)
        download_mock.assert_not_called()

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_remote_artifact_cache_hit_does_not_require_free_space_floor(self, download_mock):
        artifact_uri = "hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
        filename = "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
        cached_path = os.path.join(self.cache_dir, "28274df44091d453-%s" % filename)
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(cached_path, "wb") as handle:
            handle.write(b"cached-gguf")
        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=artifact_uri,
            quant_artifact_filename=filename,
            quant_artifact_cache_dir=self.cache_dir,
        )
        usage = mock.Mock(free=1024)
        with mock.patch.dict(os.environ, {"INFERGRADE_MIN_ARTIFACT_CACHE_FREE_GB": "1"}, clear=False):
            with mock.patch("infergrade.artifacts.shutil.disk_usage", return_value=usage):
                resolved = resolve_quant_artifact(request)
        self.assertTrue(resolved.cache_hit)
        self.assertEqual(resolved.resolved_path, cached_path)
        download_mock.assert_not_called()

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_known_sha_reuses_artifact_cached_before_sha_was_known(self, download_mock):
        artifact_uri = "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
        filename = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
        payload = b"already-cached-four-gigabyte-model"
        expected_sha = hashlib.sha256(payload).hexdigest()

        unpinned_request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=artifact_uri,
            quant_artifact_filename=filename,
            quant_artifact_cache_dir=self.cache_dir,
        )
        with mock.patch("infergrade.artifacts._download_remote_artifact") as initial_download:
            def write_cached(_url, destination_path):
                with open(destination_path, "wb") as handle:
                    handle.write(payload)

            initial_download.side_effect = write_cached
            unpinned = resolve_quant_artifact(unpinned_request)

        pinned_request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=artifact_uri,
            quant_artifact_filename=filename,
            quant_artifact_sha256=expected_sha,
            quant_artifact_revision="main",
            quant_artifact_cache_dir=self.cache_dir,
        )
        pinned = resolve_quant_artifact(pinned_request)

        self.assertTrue(pinned.cache_hit)
        self.assertEqual(pinned.resolved_path, unpinned.resolved_path)
        self.assertEqual(pinned.sha256, expected_sha)
        self.assertEqual(os.listdir(self.cache_dir), [os.path.basename(unpinned.resolved_path)])
        download_mock.assert_not_called()

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_unpinned_hf_revisions_use_distinct_cache_entries(self, download_mock):
        artifact_uri = "hf://example/model-GGUF/model.gguf"
        payloads = [b"revision-a", b"revision-b"]

        def download_next(_url, path):
            with open(path, "wb") as handle:
                handle.write(payloads.pop(0))

        download_mock.side_effect = download_next
        resolved = []
        for revision in ("revision-a", "revision-b"):
            resolved.append(
                resolve_quant_artifact(
                    RunRequest(
                        model="example/model",
                        backend="llama.cpp",
                        tier="canary",
                        quant_artifact=artifact_uri,
                        quant_artifact_revision=revision,
                        quant_artifact_cache_dir=self.cache_dir,
                    )
                )
            )

        self.assertNotEqual(resolved[0].resolved_path, resolved[1].resolved_path)
        self.assertEqual(download_mock.call_count, 2)
        self.assertIn("/resolve/revision-a/", download_mock.call_args_list[0].args[0])
        self.assertIn("/resolve/revision-b/", download_mock.call_args_list[1].args[0])

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_revision_a_cache_does_not_satisfy_pinned_revision_b(self, download_mock):
        artifact_uri = "hf://example/model-GGUF/model.gguf"
        payload_a = b"revision-a"
        payload_b = b"revision-b"

        def download_for_revision(url, path):
            payload = payload_a if "/revision-a/" in url else payload_b
            with open(path, "wb") as handle:
                handle.write(payload)

        download_mock.side_effect = download_for_revision
        resolved_a = resolve_quant_artifact(
            RunRequest(
                model="example/model",
                backend="llama.cpp",
                tier="canary",
                quant_artifact=artifact_uri,
                quant_artifact_revision="revision-a",
                quant_artifact_cache_dir=self.cache_dir,
            )
        )
        resolved_b = resolve_quant_artifact(
            RunRequest(
                model="example/model",
                backend="llama.cpp",
                tier="canary",
                quant_artifact=artifact_uri,
                quant_artifact_revision="revision-b",
                quant_artifact_sha256=hashlib.sha256(payload_b).hexdigest(),
                quant_artifact_cache_dir=self.cache_dir,
            )
        )

        self.assertNotEqual(resolved_a.resolved_path, resolved_b.resolved_path)
        self.assertFalse(resolved_b.cache_hit)
        self.assertEqual(resolved_b.sha256, hashlib.sha256(payload_b).hexdigest())
        self.assertEqual(download_mock.call_count, 2)

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_known_sha_rejects_mismatched_uri_cached_artifact_without_redownload(self, download_mock):
        artifact_uri = "https://example.test/model.gguf"
        filename = "model.gguf"
        payload = b"cached-but-wrong"
        request_without_sha = RunRequest(
            model="example/model",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=artifact_uri,
            quant_artifact_filename=filename,
            quant_artifact_cache_dir=self.cache_dir,
        )
        with mock.patch("infergrade.artifacts._download_remote_artifact") as initial_download:
            def write_cached(_url, path):
                with open(path, "wb") as handle:
                    handle.write(payload)

            initial_download.side_effect = write_cached
            resolve_quant_artifact(request_without_sha)

        pinned_request = RunRequest(
            model="example/model",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=artifact_uri,
            quant_artifact_filename=filename,
            quant_artifact_sha256=hashlib.sha256(b"expected-other-bytes").hexdigest(),
            quant_artifact_cache_dir=self.cache_dir,
        )
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            resolve_quant_artifact(pinned_request)
        download_mock.assert_not_called()

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_known_sha_reuses_checksum_keyed_cache_entry(self, download_mock):
        artifact_uri = "https://example.test/legacy-model.gguf"
        filename = "legacy-model.gguf"
        payload = b"legacy-pinned-cache-entry"
        expected_sha = hashlib.sha256(payload).hexdigest()
        legacy_path = os.path.join(self.cache_dir, "%s-%s" % (expected_sha[:16], filename))
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(legacy_path, "wb") as handle:
            handle.write(payload)

        request = RunRequest(
            model="example/model",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=artifact_uri,
            quant_artifact_filename=filename,
            quant_artifact_sha256=expected_sha,
            quant_artifact_cache_dir=self.cache_dir,
        )
        resolved = resolve_quant_artifact(request)

        self.assertTrue(resolved.cache_hit)
        self.assertEqual(resolved.resolved_path, legacy_path)
        self.assertEqual(resolved.sha256, expected_sha)
        download_mock.assert_not_called()

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_checksum_keyed_cache_entry_is_rehashed_before_reuse(self, download_mock):
        filename = "legacy-model.gguf"
        expected_sha = hashlib.sha256(b"expected-bytes").hexdigest()
        legacy_path = os.path.join(self.cache_dir, "%s-%s" % (expected_sha[:16], filename))
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(legacy_path, "wb") as handle:
            handle.write(b"tampered-bytes")

        request = RunRequest(
            model="example/model",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="https://example.test/legacy-model.gguf",
            quant_artifact_filename=filename,
            quant_artifact_sha256=expected_sha,
            quant_artifact_cache_dir=self.cache_dir,
        )
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            resolve_quant_artifact(request)
        download_mock.assert_not_called()

    @mock.patch("infergrade.artifacts._download_remote_artifact")
    def test_distinct_pinned_versions_of_same_uri_keep_distinct_cache_entries(self, download_mock):
        artifact_uri = "https://example.test/versioned-model.gguf"
        payloads = [b"revision-one", b"revision-two"]

        def download_next(_url, path):
            with open(path, "wb") as handle:
                handle.write(payloads.pop(0))

        download_mock.side_effect = download_next
        resolved_paths = []
        for payload in (b"revision-one", b"revision-two"):
            request = RunRequest(
                model="example/model",
                backend="llama.cpp",
                tier="canary",
                quant_artifact=artifact_uri,
                quant_artifact_filename="versioned-model.gguf",
                quant_artifact_sha256=hashlib.sha256(payload).hexdigest(),
                quant_artifact_cache_dir=self.cache_dir,
            )
            resolved_paths.append(resolve_quant_artifact(request).resolved_path)

        self.assertNotEqual(resolved_paths[0], resolved_paths[1])
        self.assertTrue(all(os.path.isfile(path) for path in resolved_paths))
        self.assertEqual(download_mock.call_count, 2)

    def test_concurrent_cache_publish_does_not_overwrite_first_completed_file(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        cache_path = os.path.join(self.cache_dir, "stable-model.gguf")
        losing_tmp_path = os.path.join(self.cache_dir, "infergrade-artifact-loser.tmp")
        with open(cache_path, "wb") as handle:
            handle.write(b"race-winner")
        with open(losing_tmp_path, "wb") as handle:
            handle.write(b"later-download")

        installed = _install_cache_file_without_overwrite(losing_tmp_path, cache_path)

        self.assertFalse(installed)
        with open(cache_path, "rb") as handle:
            self.assertEqual(handle.read(), b"race-winner")
        self.assertFalse(os.path.exists(losing_tmp_path))


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
