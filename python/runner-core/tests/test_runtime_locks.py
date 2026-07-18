import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.runtime_locks import (
    _build_identity,
    _canonical_sha256,
    _normalized_platform_arch,
    _package_records,
    finalize_runtime_receipt,
    resolve_runtime_lock,
)
from infergrade.runtimes import selected_llama_cpp_runtime_path


class RuntimeLockTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="infergrade-runtime-lock-")
        self.cache = Path(self.tempdir.name) / "cache"
        self.runtime_a = Path(self.tempdir.name) / "runtime-a"
        self.runtime_b = Path(self.tempdir.name) / "runtime-b"
        self.runtime_a.mkdir()
        self.runtime_b.mkdir()
        self.env_patch = mock.patch.dict(
            os.environ,
            {"INFERGRADE_RUNTIME_CACHE_DIR": str(self.cache)},
            clear=False,
        )
        self.env_patch.start()
        for name in ("INFERGRADE_LLAMA_CPP_CLI", "INFERGRADE_LLAMA_CPP_SERVER", "INFERGRADE_LLAMA_CPP_PERPLEXITY"):
            os.environ.pop(name, None)
        self._write_runtime(self.runtime_a, "a")
        self._write_runtime(self.runtime_b, "b")

    def tearDown(self):
        self.env_patch.stop()
        self.tempdir.cleanup()

    def _write_runtime(self, root: Path, marker: str) -> None:
        for name in ("llama-cli", "llama-server", "llama-perplexity"):
            path = root / name
            path.write_text("#!/bin/sh\necho %s-%s\n" % (name, marker), encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        (root / "libggml-test.dylib").write_bytes(("library-" + marker).encode("utf-8"))

    def _request(self, root: Path = None):
        root = root or self.runtime_a
        return SimpleNamespace(
            simulate=False,
            backend="llama.cpp",
            execution_mode="local_native",
            llama_cpp_cli_path=str(root / "llama-cli"),
            llama_cpp_server_path=str(root / "llama-server"),
            llama_cpp_perplexity_path=str(root / "llama-perplexity"),
        )

    def _write_managed_selection(self, root: Path) -> None:
        role_paths = {
            "cli": (root / "llama-cli").resolve(),
            "server": (root / "llama-server").resolve(),
            "perplexity": (root / "llama-perplexity").resolve(),
        }
        identity = _build_identity(_package_records(root.resolve(), role_paths), "managed_package")
        runtime_build_id = _canonical_sha256(identity)
        path = selected_llama_cpp_runtime_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "runtime_id": "managed-a",
                    "source": "managed_download",
                    "channel": "reviewed_candidate",
                    "provenance": "test managed package",
                    "archive": {"sha256": "a" * 64, "independent_signature_verified": False},
                    "runtime_build": {
                        "package_root": str(root),
                        "runtime_build_id": runtime_build_id,
                    },
                    "binaries": {
                        "cli": str(root / "llama-cli"),
                        "server": str(root / "llama-server"),
                        "perplexity": str(root / "llama-perplexity"),
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_managed_package_lock_fingerprints_full_package_without_public_paths(self):
        self._write_managed_selection(self.runtime_a)
        request = self._request()
        request.llama_cpp_cli_path = None
        request.llama_cpp_server_path = None
        request.llama_cpp_perplexity_path = None

        lock, summary = resolve_runtime_lock(request, "bundle-a")
        receipt = finalize_runtime_receipt(lock)

        self.assertEqual(summary["content_scope"], "managed_package")
        self.assertEqual(summary["origin"], "managed_download")
        self.assertEqual(receipt["content_manifest_file_count"], 4)
        self.assertIn("libggml-test.dylib", [item["relative_path"] for item in receipt["files"]])
        rendered = json.dumps(receipt, sort_keys=True)
        self.assertNotIn(self.tempdir.name, rendered)
        self.assertEqual(receipt["verification"]["silent_substitution_allowed"], False)
        lock_path = self.cache / "llama.cpp" / "locks" / (lock["runtime_lock_id"] + ".json")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

    def test_resume_restores_original_lock_after_preference_changes(self):
        request = self._request(self.runtime_a)
        lock, summary = resolve_runtime_lock(request, "bundle-resume")
        resumed_request = self._request(self.runtime_b)

        resumed_lock, resumed_summary = resolve_runtime_lock(
            resumed_request,
            "bundle-resume",
            existing_summary=summary,
        )

        self.assertEqual(resumed_summary["runtime_build_id"], summary["runtime_build_id"])
        self.assertEqual(resumed_request.llama_cpp_cli_path, str((self.runtime_a / "llama-cli").resolve()))
        self.assertEqual(resumed_lock["runtime_lock_id"], lock["runtime_lock_id"])

    def test_mutated_binary_is_rejected_instead_of_silently_relocked(self):
        request = self._request(self.runtime_a)
        lock, _summary = resolve_runtime_lock(request, "bundle-mutation")
        (self.runtime_a / "llama-server").write_text("mutated", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            finalize_runtime_receipt(lock)

    def test_failed_resume_releases_active_lock_for_explicit_cleanup(self):
        request = self._request(self.runtime_a)
        lock, summary = resolve_runtime_lock(request, "bundle-failed-resume")
        (self.runtime_a / "llama-server").write_text("mutated", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            resolve_runtime_lock(
                self._request(self.runtime_a),
                "bundle-failed-resume",
                existing_summary=summary,
            )

        lock_path = self.cache / "llama.cpp" / "locks" / (lock["runtime_lock_id"] + ".json")
        persisted = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "failed")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_managed_package_rejects_file_symlink_outside_immutable_root(self):
        outside = Path(self.tempdir.name) / "outside-library.dylib"
        outside.write_bytes(b"outside")
        os.symlink(outside, self.runtime_a / "escaped-library.dylib")
        role_paths = {
            "cli": (self.runtime_a / "llama-cli").resolve(),
            "server": (self.runtime_a / "llama-server").resolve(),
        }

        with self.assertRaisesRegex(RuntimeError, "outside its immutable root"):
            _package_records(self.runtime_a.resolve(), role_paths)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_managed_package_rejects_directory_symlink(self):
        target = self.runtime_a / "libraries"
        target.mkdir()
        os.symlink(target, self.runtime_a / "library-alias")
        role_paths = {
            "cli": (self.runtime_a / "llama-cli").resolve(),
            "server": (self.runtime_a / "llama-server").resolve(),
        }

        with self.assertRaisesRegex(RuntimeError, "directory symlinks"):
            _package_records(self.runtime_a.resolve(), role_paths)

    def test_simulated_and_container_runs_do_not_create_native_lock(self):
        request = self._request()
        request.simulate = True
        self.assertIsNone(resolve_runtime_lock(request, "bundle-simulated"))
        request.simulate = False
        request.execution_mode = "local_container"
        self.assertIsNone(resolve_runtime_lock(request, "bundle-container"))

    def test_runtime_build_identity_matches_shared_rust_fixture(self):
        fixture_path = Path("crates/runner-engine/tests/fixtures/runtime_build_identity.json")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(_canonical_sha256(fixture["identity"]), fixture["runtime_build_id"])

    def test_platform_arch_matches_rust_names(self):
        with mock.patch("infergrade.runtime_locks.platform.machine", return_value="arm64"):
            self.assertEqual(_normalized_platform_arch(), "aarch64")
        with mock.patch("infergrade.runtime_locks.platform.machine", return_value="AMD64"):
            self.assertEqual(_normalized_platform_arch(), "x86_64")

    def test_runtime_build_identity_excludes_role_assertions(self):
        role_paths = {
            "cli": (self.runtime_a / "llama-cli").resolve(),
            "server": (self.runtime_a / "llama-server").resolve(),
        }
        records = _package_records(self.runtime_a.resolve(), role_paths)
        first = _canonical_sha256(_build_identity(records, "managed_package"))
        for record in records:
            record["roles"] = ["generation"] if record["roles"] else []
        second = _canonical_sha256(_build_identity(records, "managed_package"))

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
