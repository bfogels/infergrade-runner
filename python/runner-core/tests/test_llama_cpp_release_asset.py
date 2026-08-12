import importlib.util
import io
import pathlib
import tarfile
import tempfile
import unittest
import zipfile


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
                for name in ("bin/llama-cli", "bin/llama-server", "bin/llama-perplexity"):
                    payload = name.encode("utf-8")
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    bundle.addfile(info, io.BytesIO(payload))
            members = self.module.extract_archive(archive, root / "out")
            located = self.module.locate_required(
                root / "out", ["llama-cli", "llama-server", "llama-perplexity"]
            )
        self.assertEqual(len(members), 3)
        self.assertEqual(set(located), {"llama-cli", "llama-server", "llama-perplexity"})


if __name__ == "__main__":
    unittest.main()
