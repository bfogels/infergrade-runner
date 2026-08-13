import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "write_runtime_candidate_manifest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("write_runtime_candidate_manifest", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeCandidateManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def receipt(self, platform="ubuntu-x64"):
        tag = "b10375"
        digest = "a" * 64
        return {
            "candidate_only": True,
            "upstream": {
                "release": tag,
                "url": f"https://github.com/ggml-org/llama.cpp/releases/tag/{tag}",
            },
            "platform": platform,
            "artifact": {
                "name": f"llama-{tag}-bin-{platform}.tar.gz",
                "download_url": (
                    f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/"
                    f"llama-{tag}-bin-{platform}.tar.gz"
                ),
                "size_bytes": 123,
                "github_asset_sha256": digest,
                "downloaded_sha256": digest,
                "required_members": [
                    "llama-cli",
                    "llama-completion",
                    "llama-server",
                    "llama-perplexity",
                ],
            },
            "version_smoke": {"status": "passed"},
        }

    def test_builds_candidate_only_manifest_without_catalog_assertion(self):
        manifest = self.module.build_manifest(self.receipt())
        self.assertEqual(manifest["channel"], "upstream_release")
        self.assertEqual(manifest["platform"], {"system": "linux", "arch": "x86_64"})
        self.assertIsNone(manifest["catalog_assertion"])
        self.assertEqual(manifest["archive"]["format"], "tar.gz")
        self.assertTrue(manifest["download"]["requires_explicit_user_action"])

    def test_rejects_unverified_or_windows_receipts(self):
        receipt = self.receipt()
        receipt["artifact"]["downloaded_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "digest is not verified"):
            self.module.build_manifest(receipt)

        with self.assertRaisesRegex(ValueError, "only macos-arm64 and ubuntu-x64"):
            self.module.build_manifest(self.receipt(platform="windows-cpu-x64"))

        receipt = self.receipt()
        receipt["artifact"]["name"] = "unrelated.tar.gz"
        with self.assertRaisesRegex(ValueError, "exact official release asset"):
            self.module.build_manifest(receipt)


if __name__ == "__main__":
    unittest.main()
