import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "verify_llama_cpp_model_canary.py"


def load_module():
    spec = importlib.util.spec_from_file_location("verify_llama_cpp_model_canary", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LlamaCppModelCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def archive_receipt(self, platform="ubuntu-x64", version_status="passed"):
        return {
            "receipt_version": 1,
            "candidate_only": True,
            "upstream": {"release": "b10375"},
            "platform": platform,
            "artifact": {
                "github_asset_sha256": "a" * 64,
                "downloaded_sha256": "a" * 64,
            },
            "version_smoke": {"status": version_status},
        }

    def test_requires_digest_verified_native_runtime(self):
        with self.assertRaisesRegex(ValueError, "native"):
            self.module.validate_archive_receipt(self.archive_receipt(platform="windows-cpu-x64"))
        self.module.validate_archive_receipt(self.archive_receipt(platform="macos-arm64"))
        with self.assertRaisesRegex(ValueError, "version smoke"):
            self.module.validate_archive_receipt(self.archive_receipt(version_status="not_run"))
        mismatched = self.archive_receipt()
        mismatched["artifact"]["downloaded_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "digest-verified"):
            self.module.validate_archive_receipt(mismatched)

    def test_canary_command_is_bounded_and_deterministic(self):
        command = self.module.canary_command(pathlib.Path("/runtime/llama-cli"), pathlib.Path("/tmp/model.gguf"))
        self.assertIn("8", command)
        self.assertIn("--seed", command)
        self.assertIn("1", command)
        self.assertIn("--no-display-prompt", command)
        self.assertIn("--no-conversation", command)
        self.assertIn("--single-turn", command)
        self.assertIn("--simple-io", command)
        self.assertIn("--no-warmup", command)
        self.assertIn("--no-perf", command)
        self.assertIn("--log-disable", command)
        self.assertIn("2", command)

    def test_recent_canary_comes_from_exact_bounded_policy_artifact(self):
        spec = self.module.model_spec("minicpm5_tokenizer")
        self.assertEqual(spec["repository"], "openbmb/MiniCPM5-1B-GGUF")
        self.assertEqual(spec["filename"], "MiniCPM5-1B-Q4_K_M.gguf")
        self.assertEqual(spec["size_bytes"], 688065920)
        self.assertEqual(spec["model_compatibility"], "exact_model_artifact_only")
        self.assertLessEqual(spec["size_bytes"], 1024 * 1024 * 1024)

    def test_recent_canary_rejects_unapproved_policy_id(self):
        with self.assertRaisesRegex(ValueError, "unsupported automated model canary"):
            self.module.model_spec("gemma4_consumer")

    def test_located_runtime_binary_is_absolute_for_changed_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = pathlib.Path(tmp) / "runtime"
            runtime.mkdir()
            binary = runtime / "llama-cli"
            binary.write_text("placeholder", encoding="utf-8")

            located = self.module.locate_llama_cli(pathlib.Path(tmp) / "runtime")

        self.assertTrue(located.is_absolute())
        self.assertEqual(located, binary.resolve())

    def test_receipt_keeps_legacy_canary_below_recent_architecture_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            runtime = root / "runtime"
            runtime.mkdir()
            binary = runtime / "llama-cli"
            binary.write_text("placeholder", encoding="utf-8")
            output = root / "receipt.json"

            def fake_download(destination, spec):
                destination.write_bytes(b"model")
                return spec["sha256"]

            with mock.patch.object(self.module, "download_model", side_effect=fake_download), mock.patch.object(
                self.module,
                "run_canary",
                return_value={
                    "status": "passed",
                    "elapsed_seconds": 0.1,
                    "generated_output_chars": 4,
                    "generated_output_sha256": "c" * 64,
                },
            ):
                receipt = self.module.verify(runtime, self.archive_receipt(), output)

        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["model_compatibility"], "legacy_control_only")
        self.assertIn("does not prove recent architectures", receipt["claim_boundary"])
        self.assertNotIn("runtime_dir", receipt)
        self.assertNotIn("binary_path", receipt["runtime"])

    def test_recent_receipt_stays_exact_artifact_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "llama-cli").write_text("placeholder", encoding="utf-8")
            output = root / "receipt.json"

            def fake_download(destination, spec):
                destination.write_bytes(b"model")
                return spec["sha256"]

            with mock.patch.object(self.module, "download_model", side_effect=fake_download), mock.patch.object(
                self.module,
                "run_canary",
                return_value={
                    "status": "passed",
                    "elapsed_seconds": 0.2,
                    "generated_output_chars": 8,
                    "generated_output_sha256": "d" * 64,
                },
            ):
                receipt = self.module.verify(
                    runtime,
                    self.archive_receipt(),
                    output,
                    canary_id="minicpm5_tokenizer",
                )

        self.assertEqual(receipt["canary_id"], "minicpm5_tokenizer")
        self.assertEqual(receipt["model_compatibility"], "exact_model_artifact_only")
        self.assertEqual(receipt["model"]["size_bytes"], 688065920)
        self.assertIn("exact pinned artifact", receipt["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
