import importlib.util
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "prepare_desktop_python_runtime.py"
SPEC = importlib.util.spec_from_file_location("prepare_desktop_python_runtime", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DesktopPythonRuntimeTests(unittest.TestCase):
    def test_manifest_pins_supported_desktop_targets(self):
        manifest, digest = MODULE._load_manifest(ROOT / "runtime" / "desktop_python_runtime.json")
        self.assertEqual(manifest["python_version"], "3.12.13")
        self.assertEqual(len(digest), 64)
        self.assertEqual(
            set(manifest["targets"]),
            {
                "aarch64-apple-darwin",
                "x86_64-pc-windows-msvc",
                "x86_64-unknown-linux-gnu",
            },
        )
        for target in manifest["targets"].values():
            self.assertTrue(target["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/20260728/"))
            self.assertGreater(target["size_bytes"], 1_000_000)
            self.assertRegex(target["sha256"], r"^[a-f0-9]{64}$")
            self.assertTrue(target["executable"])
            self.assertTrue(target["ca_bundle"].endswith("cacert.pem"))
            self.assertTrue(target["license"].endswith("LICENSE.txt"))

    def test_archive_guard_rejects_traversal_and_external_links(self):
        MODULE._safe_member(tarfile.TarInfo("python/bin/python3"))
        with self.assertRaises(ValueError):
            MODULE._safe_member(tarfile.TarInfo("../python/bin/python3"))
        external_link = tarfile.TarInfo("python/bin/python3")
        external_link.type = tarfile.SYMTYPE
        external_link.linkname = "../../outside"
        with self.assertRaises(ValueError):
            MODULE._safe_member(external_link)
        with self.assertRaises(ValueError):
            MODULE._safe_member(tarfile.TarInfo("python\\..\\outside"))
        external_hard_link = tarfile.TarInfo("python/deep/runtime")
        external_hard_link.type = tarfile.LNKTYPE
        external_hard_link.linkname = "../../outside"
        with self.assertRaises(ValueError):
            MODULE._safe_member(external_hard_link)

    def test_current_runtime_requires_all_integrity_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "bin" / "python3"
            executable.parent.mkdir()
            executable.write_bytes(b"runtime")
            ca_bundle = root / "certs" / "cacert.pem"
            ca_bundle.parent.mkdir()
            ca_bundle.write_bytes(b"certificate")
            license_file = root / "LICENSE.txt"
            license_file.write_bytes(b"license")
            receipt = {
                "schema_version": "infergrade.desktop_python_runtime_receipt.v1",
                "target": "test-target",
                "archive_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "executable": "bin/python3",
                "executable_sha256": MODULE._sha256(executable),
                "ca_bundle": "certs/cacert.pem",
                "ca_bundle_sha256": MODULE._sha256(ca_bundle),
                "license_path": "LICENSE.txt",
                "license_sha256": MODULE._sha256(license_file),
            }
            (root / MODULE.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
            self.assertTrue(
                MODULE._runtime_is_current(root, "test-target", "a" * 64, "b" * 64, "bin/python3")
            )
            del receipt["license_sha256"]
            (root / MODULE.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
            self.assertFalse(
                MODULE._runtime_is_current(root, "test-target", "a" * 64, "b" * 64, "bin/python3")
            )
            receipt["license_sha256"] = MODULE._sha256(license_file)
            executable.write_bytes(b"tampered")
            (root / MODULE.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
            self.assertFalse(
                MODULE._runtime_is_current(root, "test-target", "a" * 64, "b" * 64, "bin/python3")
            )

    def test_desktop_packages_prepare_and_require_the_bundled_runtime(self):
        tauri = json.loads((ROOT / "apps/desktop-runner/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        self.assertEqual(tauri["bundle"]["resources"]["desktop-python"], "python-runtime")
        self.assertTrue((ROOT / "apps/desktop-runner/src-tauri/desktop-python/.gitkeep").is_file())
        preparer = (ROOT / "apps/desktop-runner/scripts/prepare-sidecar.mjs").read_text(encoding="utf-8")
        self.assertIn("prepare_desktop_python_runtime.py", preparer)
        windows_smoke = (ROOT / "scripts/smoke_desktop_windows_packages.ps1").read_text(encoding="utf-8")
        linux_smoke = (ROOT / "scripts/smoke_desktop_linux_packages.sh").read_text(encoding="utf-8")
        self.assertIn("bundled_self_contained", windows_smoke)
        self.assertIn("Use-PythonFreePath", windows_smoke)
        self.assertIn("bundled_self_contained", linux_smoke)
        self.assertIn("INFERGRADE_PYTHON_FALLBACK_MARKER", linux_smoke)


if __name__ == "__main__":
    unittest.main()
