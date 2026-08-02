import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "prepare_desktop_python_runtime.py"
SPEC = importlib.util.spec_from_file_location("prepare_desktop_python_runtime", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.modules["prepare_desktop_python_runtime"] = MODULE
FINALIZER_PATH = ROOT / "scripts" / "finalize_desktop_linux_appimage.py"
FINALIZER_SPEC = importlib.util.spec_from_file_location("finalize_desktop_linux_appimage", FINALIZER_PATH)
FINALIZER = importlib.util.module_from_spec(FINALIZER_SPEC)
FINALIZER_SPEC.loader.exec_module(FINALIZER)


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
        linux = manifest["targets"]["x86_64-unknown-linux-gnu"]
        self.assertIn("lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so", linux["prune_paths"])

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
                "pruned_paths": ["lib/python3.12/tkinter"],
            }
            (root / MODULE.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
            self.assertTrue(
                MODULE._runtime_is_current(
                    root,
                    "test-target",
                    "a" * 64,
                    "b" * 64,
                    "bin/python3",
                    ["lib/python3.12/tkinter"],
                )
            )
            del receipt["license_sha256"]
            (root / MODULE.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
            self.assertFalse(
                MODULE._runtime_is_current(
                    root,
                    "test-target",
                    "a" * 64,
                    "b" * 64,
                    "bin/python3",
                    ["lib/python3.12/tkinter"],
                )
            )
            receipt["license_sha256"] = MODULE._sha256(license_file)
            executable.write_bytes(b"tampered")
            (root / MODULE.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
            self.assertFalse(
                MODULE._runtime_is_current(
                    root,
                    "test-target",
                    "a" * 64,
                    "b" * 64,
                    "bin/python3",
                    ["lib/python3.12/tkinter"],
                )
            )

    def test_runtime_pruning_is_explicit_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            optional_module = runtime / "lib" / "python3.12" / "tkinter"
            optional_module.mkdir(parents=True)
            (optional_module / "__init__.py").write_text("", encoding="utf-8")

            self.assertEqual(
                ["lib/python3.12/tkinter"],
                MODULE._prune_runtime(runtime, ["lib/python3.12/tkinter"]),
            )
            self.assertFalse(optional_module.exists())
            with self.assertRaises(ValueError):
                MODULE._prune_runtime(runtime, ["lib/python3.12/tkinter"])
            with self.assertRaises(ValueError):
                MODULE._prune_runtime(runtime, ["../outside"])

    def test_receipt_refresh_preserves_source_identity_and_hashes_transformed_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            executable = runtime / "bin" / "python3"
            executable.parent.mkdir()
            executable.write_bytes(b"upstream executable")
            ca_bundle = runtime / "certs" / "cacert.pem"
            ca_bundle.parent.mkdir()
            ca_bundle.write_bytes(b"certificate")
            license_file = runtime / "LICENSE.txt"
            license_file.write_bytes(b"license")
            source_digest = MODULE._sha256(executable)
            receipt = {
                "schema_version": "infergrade.desktop_python_runtime_receipt.v1",
                "executable": "bin/python3",
                "executable_sha256": source_digest,
                "ca_bundle": "certs/cacert.pem",
                "ca_bundle_sha256": MODULE._sha256(ca_bundle),
                "license_path": "LICENSE.txt",
                "license_sha256": MODULE._sha256(license_file),
            }
            (runtime / MODULE.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
            executable.write_bytes(b"linuxdeploy transformed executable")

            refreshed = MODULE.refresh_runtime_receipt(runtime, "linuxdeploy_appimage_v1")
            self.assertEqual(refreshed["source_executable_sha256"], source_digest)
            self.assertEqual(refreshed["executable_sha256"], MODULE._sha256(executable))
            self.assertEqual(refreshed["packaging_transforms"], ["linuxdeploy_appimage_v1"])

            repeated = MODULE.refresh_runtime_receipt(runtime, "linuxdeploy_appimage_v1")
            self.assertEqual(repeated["source_executable_sha256"], source_digest)
            self.assertEqual(repeated["packaging_transforms"], ["linuxdeploy_appimage_v1"])

    def test_appimage_finalizer_rebuilds_from_resealed_appdir(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            app_dir = bundle / "InferGrade Runner.AppDir"
            runtime = app_dir / "usr" / "lib" / "InferGrade Runner" / "python-runtime"
            executable = runtime / "bin" / "python3"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"transformed")
            ca_bundle = runtime / "certs" / "cacert.pem"
            ca_bundle.parent.mkdir()
            ca_bundle.write_bytes(b"certificate")
            license_file = runtime / "LICENSE.txt"
            license_file.write_bytes(b"license")
            (runtime / MODULE.RECEIPT_NAME).write_text(
                json.dumps(
                    {
                        "schema_version": "infergrade.desktop_python_runtime_receipt.v1",
                        "executable": "bin/python3",
                        "executable_sha256": "a" * 64,
                        "ca_bundle": "certs/cacert.pem",
                        "ca_bundle_sha256": MODULE._sha256(ca_bundle),
                        "license_path": "LICENSE.txt",
                        "license_sha256": MODULE._sha256(license_file),
                    }
                ),
                encoding="utf-8",
            )
            appimage = bundle / "InferGrade Runner_0.3.49_amd64.AppImage"
            appimage.write_bytes(b"unsealed")
            plugin = bundle / "tools" / "linuxdeploy-plugin-appimage.AppImage"
            plugin.parent.mkdir()
            plugin.write_bytes(b"plugin")
            calls = []

            def fake_runner(command, check, env):
                calls.append((command, check, env))
                Path(env["LDAI_OUTPUT"]).write_bytes(b"resealed")

            result = FINALIZER.finalize_appimage(bundle, plugin, runner=fake_runner)
            self.assertEqual(result, appimage)
            self.assertEqual(appimage.read_bytes(), b"resealed")
            self.assertEqual(calls[0][0][-2:], ["--appdir", str(app_dir)])
            self.assertEqual(calls[0][2]["APPIMAGE_EXTRACT_AND_RUN"], "1")
            refreshed = json.loads((runtime / MODULE.RECEIPT_NAME).read_text(encoding="utf-8"))
            self.assertEqual(refreshed["executable_sha256"], MODULE._sha256(executable))
            self.assertEqual(refreshed["packaging_transforms"], [FINALIZER.TRANSFORM])

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
        package = json.loads((ROOT / "apps/desktop-runner/package.json").read_text(encoding="utf-8"))
        self.assertIn("finalize_desktop_linux_appimage.py", package["scripts"]["build:linux"])


if __name__ == "__main__":
    unittest.main()
