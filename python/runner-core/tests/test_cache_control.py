import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from infergrade.cache_control import (
    clear_unkept,
    managed_status,
    process_lock,
    record_install,
    request_cache_lease,
    set_keep,
)


class CacheControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def install(self, name="owned.gguf"):
        path = self.root / name
        path.write_bytes(b"managed model")
        return path, record_install(self.root, path, "a" * 64)

    def test_unowned_partial_external_link_and_kept_files_are_preserved(self):
        owned, artifact_id = self.install()
        unknown = self.root / "old.gguf"
        unknown.write_bytes(b"legacy")
        partial = self.root / "infergrade-artifact-active.tmp"
        partial.write_bytes(b"download")
        outside = self.root / "outside"
        outside.mkdir()
        external = outside / "model.gguf"
        external.write_bytes(b"external")
        if hasattr(os, "symlink"):
            try:
                (self.root / "linked.gguf").symlink_to(external)
            except OSError:
                pass
        set_keep(artifact_id, True, self.root)
        self.assertEqual(0, clear_unkept(self.root)["removed_count"])
        set_keep(artifact_id, False, self.root)
        self.assertEqual(1, clear_unkept(self.root)["removed_count"])
        self.assertFalse(owned.exists())
        self.assertTrue(unknown.exists() and partial.exists() and external.exists())

    def test_replaced_or_modified_managed_file_is_not_deleted(self):
        path, _ = self.install()
        path.write_bytes(b"changed ownership")
        self.assertFalse(managed_status(self.root)["artifacts"][0]["managed"])
        self.assertEqual(0, clear_unkept(self.root)["removed_count"])
        self.assertTrue(path.exists())

    def test_subprocess_reader_blocks_deletion_and_crash_releases_lease(self):
        path, _ = self.install()
        code = 'import sys,time;from infergrade.cache_control import process_lock\nwith process_lock(sys.argv[1]):\n print("leased",flush=True)\n time.sleep(60)'
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(self.root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        self.assertEqual("leased", child.stdout.readline().strip())
        with self.assertRaisesRegex(RuntimeError, "Cache is in use"):
            clear_unkept(self.root)
        child.kill()
        child.communicate(timeout=10)
        self.assertEqual(1, clear_unkept(self.root)["removed_count"])
        self.assertFalse(path.exists())

    def test_two_readers_and_serialized_keep_metadata(self):
        path, artifact_id = self.install()
        with process_lock(self.root), process_lock(self.root):
            set_keep(artifact_id, True, self.root)
            self.assertTrue(managed_status(self.root)["artifacts"][0]["keep"])
        self.assertEqual(0, clear_unkept(self.root)["removed_count"])
        self.assertTrue(path.exists())

    def test_invalid_metadata_and_path_ids_fail_closed(self):
        path, _ = self.install()
        with self.assertRaises(ValueError):
            clear_unkept(self.root, "../owned.gguf")
        (self.root / ".infergrade-cache-control" / "managed.json").write_text(
            json.dumps([])
        )
        with self.assertRaises(RuntimeError):
            clear_unkept(self.root)
        self.assertTrue(path.exists())

    def test_local_managed_path_and_custom_host_cache_are_leased(self):
        from infergrade.cache_control import _roots
        from infergrade.models import RunRequest

        self.install()
        request = RunRequest(
            model="m",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=str(self.root / "owned.gguf"),
        )
        self.assertIn(str(self.root), _roots(request))
        request.quant_artifact_cache_dir = str(self.root)
        self.assertIn(str(self.root), _roots(request))

    def test_file_uri_is_leased_before_reading_custom_managed_artifact(self):
        from infergrade.models import RunRequest

        path, _ = self.install("custom owned.gguf")
        request = RunRequest(
            model="m",
            backend="llama.cpp",
            tier="canary",
            quant_artifact=path.as_uri(),
            simulate=False,
        )
        with request_cache_lease(request):
            with self.assertRaisesRegex(RuntimeError, "Cache is in use"):
                clear_unkept(self.root)
            self.assertTrue(path.exists())
        self.assertEqual(1, clear_unkept(self.root)["removed_count"])

    def test_alias_into_custom_managed_cache_is_leased(self):
        from infergrade.models import RunRequest

        path, _ = self.install()
        with tempfile.TemporaryDirectory() as d:
            alias = Path(d) / "alias.gguf"
            try:
                alias.symlink_to(path)
            except OSError:
                self.skipTest("Creating file symlinks is unavailable")
            request = RunRequest(
                model="m",
                backend="llama.cpp",
                tier="canary",
                quant_artifact=str(alias),
                simulate=False,
            )
            with request_cache_lease(request):
                with self.assertRaisesRegex(RuntimeError, "Cache is in use"):
                    clear_unkept(self.root)
            self.assertEqual(1, clear_unkept(self.root)["removed_count"])
