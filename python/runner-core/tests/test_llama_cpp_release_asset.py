import importlib.util
import io
import pathlib
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "verify_llama_cpp_release_asset.py"


def load_module():
    spec = importlib.util.spec_from_file_location("verify_llama_cpp_release_asset", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LlamaCppReleaseAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def release(self, tag="b10375"):
        name = f"llama-{tag}-bin-macos-arm64.tar.gz"
        return {
            "tag_name": tag,
            "published_at": "2026-08-12T00:00:00Z",
            "html_url": f"https://github.com/ggml-org/llama.cpp/releases/tag/{tag}",
            "assets": [{
                "name": name,
                "size": 123,
                "digest": f"sha256:{'a' * 64}",
                "browser_download_url": f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{name}",
            }],
        }

    def test_selects_only_the_exact_official_platform_asset(self):
        name, asset, required = self.module.release_asset(self.release(), "macos-arm64")
        self.assertEqual(name, "llama-b10375-bin-macos-arm64.tar.gz")
        self.assertEqual(asset["size"], 123)
        self.assertIn("llama-cli", required)
        self.assertIn("llama-completion", required)

    def test_rejects_non_llama_release_tags(self):
        with self.assertRaisesRegex(ValueError, "bNNNN"):
            self.module.release_asset(self.release(tag="latest"), "macos-arm64")

    def test_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../llama-cli.exe", b"unsafe")
            with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                self.module.extract_archive(archive, root / "out")

    def test_rejects_unsafe_tar_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("llama-cli")
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp/elsewhere"
                bundle.addfile(info)
            with self.assertRaisesRegex(ValueError, "unsafe archive link"):
                self.module.extract_archive(archive, root / "out")

    def test_extracts_a_bounded_expected_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            archive = root / "tools.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                for name in (
                    "bin/llama-cli",
                    "bin/llama-completion",
                    "bin/llama-server",
                    "bin/llama-perplexity",
                ):
                    payload = name.encode("utf-8")
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))
            members = self.module.extract_archive(archive, root / "out")
            located = self.module.locate_required(
                root / "out",
                ["llama-cli", "llama-completion", "llama-server", "llama-perplexity"],
            )
        self.assertEqual(len(members), 4)
        self.assertEqual(
            set(located),
            {"llama-cli", "llama-completion", "llama-server", "llama-perplexity"},
        )

    def test_can_retain_verified_runtime_for_same_job_model_canary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source_archive = root / "source.tar.gz"
            with tarfile.open(source_archive, "w:gz") as bundle:
                for name in (
                    "bin/llama-cli",
                    "bin/llama-completion",
                    "bin/llama-server",
                    "bin/llama-perplexity",
                ):
                    payload = name.encode("utf-8")
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    info.mode = 0o755
                    bundle.addfile(info, io.BytesIO(payload))
            retained = root / "retained"
            output = root / "receipt.json"

            def fake_download(_url, destination, _size):
                shutil.copyfile(source_archive, destination)
                return "a" * 64

            with mock.patch.object(self.module, "download_asset", side_effect=fake_download):
                receipt = self.module.verify(
                    self.release(),
                    "macos-arm64",
                    output,
                    False,
                    retained_runtime_dir=retained,
                )
            self.assertTrue(receipt["runtime_materialized_for_canary"])
            self.assertTrue((retained / "bin" / "llama-cli").is_file())

    def test_retries_transient_download_errors_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = pathlib.Path(tmp) / "runtime.tar.gz"
            attempts = 0

            def flaky_download(_url, path, _size):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    path.write_bytes(b"partial")
                    raise ConnectionResetError("connection closed")
                self.assertFalse(path.exists())
                path.write_bytes(b"complete")
                return "digest"

            with mock.patch.object(
                self.module,
                "_download_asset_once",
                side_effect=flaky_download,
            ):
                with mock.patch.object(self.module.time, "sleep") as sleep:
                    digest = self.module.download_asset(
                        "https://example.invalid/runtime",
                        destination,
                        8,
                    )

        self.assertEqual(digest, "digest")
        self.assertEqual(attempts, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_does_not_retry_integrity_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = pathlib.Path(tmp) / "runtime.tar.gz"
            with mock.patch.object(
                self.module,
                "_download_asset_once",
                side_effect=ValueError("download size mismatch"),
            ) as download:
                with self.assertRaisesRegex(ValueError, "size mismatch"):
                    self.module.download_asset("https://example.invalid/runtime", destination, 8)

        download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
