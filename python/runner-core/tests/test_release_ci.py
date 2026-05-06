import contextlib
import io
import json
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from scripts.sync_versions import sync_versions
from scripts.write_desktop_release_checksums import main as write_desktop_release_checksums
from scripts.write_desktop_update_manifest import main as write_desktop_update_manifest


ROOT = Path(__file__).resolve().parents[3]


class ReleaseCiTests(unittest.TestCase):
    def test_release_bundle_workflow_runs_on_main_push(self):
        workflow = (ROOT / ".github" / "workflows" / "release-bundle.yml").read_text(encoding="utf-8")

        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("./scripts/build_release_bundle.sh", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("infergrade-runner-release-${{ steps.release_bundle.outputs.release_version }}", workflow)

    def test_release_bundle_script_defaults_to_version_preview(self):
        script = (ROOT / "scripts" / "build_release_bundle.sh").read_text(encoding="utf-8")

        self.assertIn('VERSION_TAG="${INFERGRADE_RELEASE_VERSION:-$(<"${ROOT_DIR}/VERSION")-preview}"', script)
        self.assertIn("python3 ./scripts/check_versions.py", script)
        self.assertIn('python3 ./scripts/export_release_bundle.py --release-version "${VERSION_TAG}"', script)
        self.assertNotIn("0.1.0-preview", script)

    def test_release_image_scripts_default_to_version_preview(self):
        for relative_path in ("scripts/build_release_images.sh", "scripts/export_release_images.sh"):
            script = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('VERSION_TAG="${INFERGRADE_IMAGE_TAG:-$(<"${ROOT_DIR}/VERSION")-preview}"', script)
            self.assertNotIn("0.1.0-preview", script)

    def test_ci_checks_version_sync_before_running_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python3 ./scripts/sync_versions.py --check", workflow)
        self.assertIn("python3 ./scripts/check_versions.py", workflow)

    def test_publish_container_workflow_defaults_to_version_file_at_runtime(self):
        workflow = (ROOT / ".github" / "workflows" / "publish-containers.yml").read_text(encoding="utf-8")

        self.assertIn('default: ""', workflow)
        self.assertIn('image_tag="$(cat VERSION)-preview"', workflow)
        self.assertNotIn("0.1.31-preview", workflow)

    def test_desktop_app_uses_package_metadata_for_browser_version_fallback(self):
        js = (ROOT / "apps" / "desktop-runner" / "src" / "main.js").read_text(encoding="utf-8")
        html = (ROOT / "apps" / "desktop-runner" / "index.html").read_text(encoding="utf-8")

        self.assertIn('import packageInfo from "../package.json"', js)
        self.assertIn("const APP_VERSION_FALLBACK = packageInfo.version;", js)
        self.assertNotIn('APP_VERSION_FALLBACK = "0.1.', js)
        self.assertIn("<strong data-app-version>checking...</strong>", html)
        self.assertNotIn("<strong data-app-version>0.1.", html)

    def test_sync_versions_updates_required_manifest_copies_from_version_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / "python/runner-core",
                root / "python/runner-core/src/infergrade",
                root / "apps/desktop-runner/src-tauri",
            ]
            for path in paths:
                path.mkdir(parents=True)
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            (root / "python/runner-core/pyproject.toml").write_text('version = "0.0.1"\n', encoding="utf-8")
            (root / "python/runner-core/setup.py").write_text('version="0.0.1",\n', encoding="utf-8")
            (root / "python/runner-core/src/infergrade/__init__.py").write_text(
                '__version__ = "0.0.1"\n', encoding="utf-8"
            )
            (root / "apps/desktop-runner/package.json").write_text(
                '{"name":"infergrade-desktop-runner","version":"0.0.1"}\n', encoding="utf-8"
            )
            (root / "apps/desktop-runner/package-lock.json").write_text(
                '{"name":"infergrade-desktop-runner","version":"0.0.1","packages":{"":{"version":"0.0.1"}}}\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/tauri.conf.json").write_text(
                '{"productName":"InferGrade Runner","version":"0.0.1"}\n', encoding="utf-8"
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.toml").write_text(
                '[package]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.lock").write_text(
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n'
                '[[package]]\nname = "schannel"\nversion = "0.1.29"\n',
                encoding="utf-8",
            )

            changed = sync_versions(root)

            self.assertIn("python/runner-core/pyproject.toml", changed)
            self.assertIn('version = "1.2.3"', (root / "python/runner-core/pyproject.toml").read_text())
            self.assertIn('version="1.2.3"', (root / "python/runner-core/setup.py").read_text())
            self.assertIn('__version__ = "1.2.3"', (root / "python/runner-core/src/infergrade/__init__.py").read_text())
            self.assertEqual(
                "1.2.3",
                json.loads((root / "apps/desktop-runner/package.json").read_text(encoding="utf-8"))["version"],
            )
            self.assertEqual(
                "1.2.3",
                json.loads((root / "apps/desktop-runner/package-lock.json").read_text(encoding="utf-8"))["packages"][
                    ""
                ]["version"],
            )
            self.assertIn('version = "1.2.3"', (root / "apps/desktop-runner/src-tauri/Cargo.toml").read_text())
            cargo_lock = (root / "apps/desktop-runner/src-tauri/Cargo.lock").read_text()
            self.assertIn('name = "infergrade_desktop_runner"\nversion = "1.2.3"', cargo_lock)
            self.assertIn('name = "schannel"\nversion = "0.1.29"', cargo_lock)

    def test_sync_versions_fails_instead_of_rewriting_dependency_lock_versions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / "python/runner-core",
                root / "python/runner-core/src/infergrade",
                root / "apps/desktop-runner/src-tauri",
            ]
            for path in paths:
                path.mkdir(parents=True)
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            (root / "python/runner-core/pyproject.toml").write_text('version = "0.0.1"\n', encoding="utf-8")
            (root / "python/runner-core/setup.py").write_text('version="0.0.1",\n', encoding="utf-8")
            (root / "python/runner-core/src/infergrade/__init__.py").write_text(
                '__version__ = "0.0.1"\n', encoding="utf-8"
            )
            (root / "apps/desktop-runner/package.json").write_text(
                '{"name":"infergrade-desktop-runner","version":"0.0.1"}\n', encoding="utf-8"
            )
            lockfile = (
                '{"name":"infergrade-desktop-runner","version":"0.0.1","packages":{'
                '"node_modules/dependency":{"version":"9.9.9"}}}\n'
            )
            lock_path = root / "apps/desktop-runner/package-lock.json"
            lock_path.write_text(lockfile, encoding="utf-8")
            (root / "apps/desktop-runner/src-tauri/tauri.conf.json").write_text(
                '{"$schema":"https://schema.tauri.app/config/2","productName":"InferGrade Runner","version":"0.0.1"}\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.toml").write_text(
                '[package]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.lock").write_text(
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "root package entry"):
                sync_versions(root)
            self.assertEqual(lockfile, lock_path.read_text(encoding="utf-8"))

    def test_sync_versions_dry_run_reports_changes_without_writing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / "python/runner-core",
                root / "python/runner-core/src/infergrade",
                root / "apps/desktop-runner/src-tauri",
            ]
            for path in paths:
                path.mkdir(parents=True)
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            (root / "python/runner-core/pyproject.toml").write_text('version = "0.0.1"\n', encoding="utf-8")
            (root / "python/runner-core/setup.py").write_text('version="0.0.1",\n', encoding="utf-8")
            (root / "python/runner-core/src/infergrade/__init__.py").write_text(
                '__version__ = "0.0.1"\n', encoding="utf-8"
            )
            (root / "apps/desktop-runner/package.json").write_text(
                '{"name":"infergrade-desktop-runner","version":"0.0.1"}\n', encoding="utf-8"
            )
            (root / "apps/desktop-runner/package-lock.json").write_text(
                '{"name":"infergrade-desktop-runner","version":"0.0.1","packages":{"":{"version":"0.0.1"}}}\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/tauri.conf.json").write_text(
                '{"productName":"InferGrade Runner","version":"0.0.1"}\n', encoding="utf-8"
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.toml").write_text(
                '[package]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.lock").write_text(
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )

            changed = sync_versions(root, dry_run=True)

            self.assertIn("python/runner-core/pyproject.toml", changed)
            self.assertIn('version = "0.0.1"', (root / "python/runner-core/pyproject.toml").read_text())

    def test_desktop_release_workflow_publishes_latest_dmg_on_main_push(self):
        workflow = (ROOT / ".github" / "workflows" / "desktop-runner-release.yml").read_text(encoding="utf-8")

        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn('description: "SemVer desktop app version to publish; defaults to VERSION on main"', workflow)
        self.assertIn('default: ""', workflow)
        self.assertIn('DESKTOP_VERSION="$(cat VERSION)"', workflow)
        self.assertNotIn('default: "0.1.', workflow)
        self.assertIn("RELEASE_TAG: desktop-runner-latest", workflow)
        self.assertIn("./scripts/build_desktop_runner.sh --check-only", workflow)
        self.assertIn("./scripts/build_desktop_runner.sh --with-updater --skip-checks", workflow)
        self.assertIn("./scripts/verify_desktop_macos_release.sh", workflow)
        self.assertIn("target/release/bundle/dmg/*.dmg", workflow)
        self.assertIn("./scripts/notarize_desktop_dmg.sh", workflow)
        self.assertLess(
            workflow.index("./scripts/notarize_desktop_dmg.sh"),
            workflow.index("./scripts/verify_desktop_macos_release.sh"),
        )
        self.assertIn("./scripts/write_desktop_release_checksums.py", workflow)
        self.assertIn("target/release/bundle/macos/SHA256SUMS", workflow)
        self.assertIn("gh release upload", workflow)

    def test_desktop_release_workflow_smokes_windows_and_linux_packages(self):
        workflow = (ROOT / ".github" / "workflows" / "desktop-runner-release.yml").read_text(encoding="utf-8")

        self.assertIn("permissions:\n  contents: read\n\njobs:", workflow)
        self.assertIn("macos-preview:\n    name: Build and publish macOS desktop app\n    runs-on: macos-latest\n    permissions:\n      contents: write", workflow)
        self.assertIn("windows-package-smoke:", workflow)
        self.assertIn("linux-package-smoke:", workflow)
        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn("runs-on: ubuntu-22.04", workflow)
        self.assertIn("windows-package-smoke:\n    name: Build Windows desktop packages\n    runs-on: windows-latest\n    permissions:\n      contents: read", workflow)
        self.assertIn("linux-package-smoke:\n    name: Build Linux desktop packages\n    runs-on: ubuntu-22.04\n    permissions:\n      contents: read", workflow)
        self.assertIn("npm run build:windows", workflow)
        self.assertIn("npm run build:linux", workflow)
        self.assertIn("libwebkit2gtk-4.1-dev", workflow)
        self.assertIn("libayatana-appindicator3-dev", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("infergrade-runner-desktop-windows-${{ github.sha }}", workflow)
        self.assertIn("infergrade-runner-desktop-linux-${{ github.sha }}", workflow)
        self.assertIn("target/release/bundle/nsis/*.exe", workflow)
        self.assertIn("target/release/bundle/msi/*.msi", workflow)
        self.assertIn("target/release/bundle/deb/*.deb", workflow)
        self.assertIn("target/release/bundle/appimage/*.AppImage", workflow)
        self.assertNotIn("target/release/bundle/rpm/*", workflow)

    def test_desktop_package_smokes_upload_checksums_with_artifacts(self):
        workflow = (ROOT / ".github" / "workflows" / "desktop-runner-release.yml").read_text(encoding="utf-8")

        self.assertEqual(workflow.count("./scripts/write_desktop_release_checksums.py"), 3)
        self.assertIn("target/release/bundle/windows/SHA256SUMS", workflow)
        self.assertIn("target/release/bundle/linux/SHA256SUMS", workflow)
        self.assertIn("actions/setup-python@v5", workflow)
        self.assertIn('python-version: "3.12"', workflow)
        self.assertIn("target/release/bundle/nsis/*.exe", workflow)
        self.assertIn("target/release/bundle/msi/*.msi", workflow)
        self.assertIn("target/release/bundle/deb/*.deb", workflow)
        self.assertIn("target/release/bundle/appimage/*.AppImage", workflow)
        self.assertIn("target/release/bundle/windows/SHA256SUMS", workflow)
        self.assertIn("target/release/bundle/linux/SHA256SUMS", workflow)

    def test_desktop_release_docs_match_protected_signing_and_notarization_gate(self):
        docs = (ROOT / "docs" / "release_process.md").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "desktop-runner-release.yml").read_text(encoding="utf-8")

        self.assertIn("Verify signing and notarization inputs", workflow)
        self.assertIn("TAURI_SIGNING_PRIVATE_KEY", workflow)
        self.assertIn("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", workflow)
        self.assertIn("APPLE_CERTIFICATE", workflow)
        self.assertIn("APPLE_CERTIFICATE_PASSWORD", workflow)
        self.assertIn("APPLE_ID", workflow)
        self.assertIn("APPLE_PASSWORD", workflow)
        self.assertIn("APPLE_API_KEY", workflow)
        self.assertIn("APPLE_API_ISSUER", workflow)
        self.assertIn("APPLE_API_PRIVATE_KEY", workflow)
        self.assertIn("APPLE_API_KEY_PATH", workflow)
        self.assertIn("secrets.APPLE_SIGNING_IDENTITY", workflow)
        self.assertNotIn("APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}", workflow)
        self.assertIn("APPLE_TEAM_ID", workflow)
        self.assertIn("INFERGRADE_MACOS_SIGNING_IDENTITY", workflow)
        self.assertIn("Missing desktop release signing/notarization input(s)", workflow)
        self.assertIn('INFERGRADE_MACOS_SIGNING_IDENTITY" = "-"', workflow)
        self.assertIn("Check desktop app dependencies", workflow)
        self.assertIn("Validate Apple signing certificate password", workflow)
        self.assertIn("infergrade-release-certificate.p12", workflow)
        self.assertIn("openssl pkcs12", workflow)
        self.assertIn("-passin env:APPLE_CERTIFICATE_PASSWORD", workflow)
        self.assertIn("openssl pkcs12 -legacy", workflow)
        self.assertNotIn("-passin \"pass:$APPLE_CERTIFICATE_PASSWORD\"", workflow)
        self.assertIn("APPLE_CERTIFICATE could not be opened with APPLE_CERTIFICATE_PASSWORD", workflow)
        self.assertIn("Prepare App Store Connect API key", workflow)
        self.assertIn('if [ "$APPLE_NOTARIZATION_MODE" != "api_key" ]', workflow)
        self.assertIn('key_path="$RUNNER_TEMP/AuthKey_${APPLE_API_KEY}.p8"', workflow)
        self.assertIn("APPLE_NOTARIZATION_MODE=api_key", workflow)
        self.assertIn("APPLE_NOTARIZATION_MODE=apple_id", workflow)
        self.assertIn("must not fall back to ad-hoc signing or skip notarization", workflow)
        self.assertGreaterEqual(workflow.count("exit 1"), 2)
        self.assertIn("must not fall back to ad-hoc macOS signing or skip notarization", docs)
        self.assertIn("App Store Connect API-key credentials", docs)
        self.assertIn("Gatekeeper assessment", docs)
        self.assertIn("Local developer builds can still use ad-hoc signing", docs)
        self.assertIn("Recover A Certificate Secret Failure", docs)
        self.assertIn("Validate Apple signing certificate password", docs)
        self.assertIn("fix the certificate and password as a pair", docs)
        self.assertIn("openssl pkcs12 -in ~/Desktop/infergrade-developer-id-application.p12", docs)
        self.assertIn("base64 -i ~/Desktop/infergrade-developer-id-application.p12 | tr -d '\\n'", docs)
        self.assertIn("update the certificate and password secrets together", docs)
        distribution_docs = (ROOT / "docs" / "desktop_runner_distribution.md").read_text(encoding="utf-8")
        app_readme = (ROOT / "apps" / "desktop-runner" / "README.md").read_text(encoding="utf-8")
        self.assertIn("could not be opened with `APPLE_CERTIFICATE_PASSWORD`", app_readme)
        self.assertIn("verify it locally with `openssl pkcs12 -passin env:APPLE_CERTIFICATE_PASSWORD`", app_readme)
        for release_doc in (docs, distribution_docs, app_readme):
            self.assertIn("damaged and can't be opened", release_doc)
            self.assertIn("Do not ask users to bypass Gatekeeper", release_doc)
        self.assertNotIn("falls back to ad-hoc macOS signing only when Apple Developer ID credentials are absent", docs)
        self.assertNotIn("No Apple notarization credential was provided", workflow)

    def test_desktop_release_verification_checks_gatekeeper_and_stapled_tickets(self):
        script = (ROOT / "scripts" / "verify_desktop_macos_release.sh").read_text(encoding="utf-8")

        self.assertIn('if [ "$(uname -s)" != "Darwin" ]', script)
        self.assertIn("codesign --verify --deep --strict --verbose=2", script)
        self.assertIn("spctl --assess --type execute --verbose=4", script)
        self.assertIn("spctl --assess --type open --context context:primary-signature --verbose=4", script)
        self.assertEqual(script.count("xcrun stapler validate"), 2)
        self.assertIn("Expected exactly one macOS app bundle", script)
        self.assertIn("Expected exactly one macOS DMG", script)

    def test_desktop_dmg_notarization_script_submits_and_staples_dmg(self):
        script_path = ROOT / "scripts" / "notarize_desktop_dmg.sh"

        self.assertTrue(script_path.exists())
        script = script_path.read_text(encoding="utf-8")
        self.assertIn('if [ "$(uname -s)" != "Darwin" ]', script)
        self.assertIn("Expected exactly one macOS DMG", script)
        self.assertIn("xcrun notarytool submit", script)
        self.assertIn("--wait", script)
        self.assertIn("--key \"$APPLE_API_KEY_PATH\"", script)
        self.assertIn("--key-id \"$APPLE_API_KEY\"", script)
        self.assertIn("--issuer \"$APPLE_API_ISSUER\"", script)
        self.assertIn("--apple-id \"$APPLE_ID\"", script)
        self.assertIn("--password \"$APPLE_PASSWORD\"", script)
        self.assertIn("--team-id \"$APPLE_TEAM_ID\"", script)
        self.assertIn("xcrun stapler staple \"$dmg\"", script)

    def test_desktop_build_script_ignores_empty_apple_signing_env(self):
        script = (ROOT / "scripts" / "build_desktop_runner.sh").read_text(encoding="utf-8")

        self.assertIn("unset_if_empty APPLE_CERTIFICATE", script)
        self.assertIn("unset_if_empty APPLE_CERTIFICATE_PASSWORD", script)
        self.assertIn("unset_if_empty APPLE_ID", script)
        self.assertIn("unset APPLE_ID", script)
        self.assertIn("unset APPLE_PASSWORD", script)
        self.assertIn("--check-only", script)
        self.assertIn("--skip-checks", script)
        self.assertIn('MACOS_SIGNING_IDENTITY="-"', script)

    def test_desktop_build_generates_platform_sidecar_from_source(self):
        build_script = (ROOT / "scripts" / "build_desktop_runner.sh").read_text(encoding="utf-8")
        sidecar_script_path = ROOT / "scripts" / "build_desktop_sidecar.sh"
        sidecar_manifest_path = ROOT / "apps" / "desktop-runner" / "sidecar" / "Cargo.toml"
        sidecar_source_path = ROOT / "apps" / "desktop-runner" / "sidecar" / "src" / "main.rs"
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertTrue(sidecar_script_path.exists())
        sidecar_script = sidecar_script_path.read_text(encoding="utf-8")
        self.assertTrue(sidecar_manifest_path.exists())
        self.assertTrue(sidecar_source_path.exists())
        self.assertIn("build_desktop_sidecar.sh", build_script)
        self.assertIn("rustc -Vv", sidecar_script)
        self.assertIn("host:", sidecar_script)
        self.assertIn("infergrade-sidecar-${TARGET_TRIPLE}${EXE_SUFFIX}", sidecar_script)
        self.assertIn("x86_64-pc-windows-msvc", sidecar_script)
        self.assertIn("apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-*", gitignore)

    def test_desktop_release_checksums_manifest_is_deterministic(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dmg = root / "InferGrade Runner_0.1.13_aarch64.dmg"
            archive = root / "InferGrade.Runner.app.tar.gz"
            signature = root / "InferGrade.Runner.app.tar.gz.sig"
            manifest = root / "infergrade-runner-desktop-latest.json"
            output = root / "SHA256SUMS"
            dmg.write_bytes(b"dmg")
            archive.write_bytes(b"archive")
            signature.write_bytes(b"signature")
            manifest.write_text('{"version":"0.1.13"}\n', encoding="utf-8")

            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_release_checksums",
                    "--output",
                    str(output),
                    str(signature),
                    str(dmg),
                    str(manifest),
                    str(archive),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(write_desktop_release_checksums(), 0)
            finally:
                sys.argv = old_argv

            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [line.split("  ", 1)[1] for line in lines],
                [
                    "InferGrade Runner_0.1.13_aarch64.dmg",
                    "InferGrade.Runner.app.tar.gz",
                    "InferGrade.Runner.app.tar.gz.sig",
                    "infergrade-runner-desktop-latest.json",
                ],
            )
            self.assertTrue(all(len(line.split("  ", 1)[0]) == 64 for line in lines))

    def test_desktop_release_checksums_ignore_packager_staging_directories(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            deb = root / "InferGrade Runner_0.1.30_amd64.deb"
            appimage = root / "InferGrade Runner_0.1.30_amd64.AppImage"
            deb_staging = root / "InferGrade Runner_0.1.30_amd64"
            appimage_staging = root / "InferGrade Runner.AppDir"
            output = root / "SHA256SUMS"
            deb.write_bytes(b"deb")
            appimage.write_bytes(b"appimage")
            deb_staging.mkdir()
            appimage_staging.mkdir()

            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_release_checksums",
                    "--output",
                    str(output),
                    str(deb_staging),
                    str(appimage_staging),
                    str(deb),
                    str(appimage),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(write_desktop_release_checksums(), 0)
            finally:
                sys.argv = old_argv

            names = [line.split("  ", 1)[1] for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(names, [appimage.name, deb.name])

    def test_desktop_release_checksums_fails_when_only_directories_are_provided(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "InferGrade Runner.AppDir"
            staging.mkdir()
            output = root / "SHA256SUMS"

            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_release_checksums",
                    "--output",
                    str(output),
                    str(staging),
                ]
                with self.assertRaises(SystemExit) as raised:
                    write_desktop_release_checksums()
            finally:
                sys.argv = old_argv

            self.assertIn("No release artifacts", str(raised.exception))
            self.assertFalse(output.exists())

    def test_desktop_release_checksums_fails_for_missing_artifacts(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "SHA256SUMS"
            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_release_checksums",
                    "--output",
                    str(output),
                    str(Path(tmp) / "missing.dmg"),
                ]
                with self.assertRaises(SystemExit) as raised:
                    write_desktop_release_checksums()
            finally:
                sys.argv = old_argv

            self.assertIn("Missing release artifact", str(raised.exception))
            self.assertFalse(output.exists())

    def test_desktop_update_manifest_quotes_archive_url_and_preserves_metadata(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()
            archive = bundle_dir / "InferGrade Runner.app.tar.gz"
            signature = bundle_dir / "InferGrade Runner.app.tar.gz.sig"
            output = root / "latest.json"
            archive.write_bytes(b"archive")
            signature.write_text("trusted-signature\n", encoding="utf-8")

            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_update_manifest",
                    "--bundle-dir",
                    str(bundle_dir),
                    "--version",
                    "0.1.13",
                    "--base-url",
                    "https://example.test/releases/",
                    "--notes",
                    "Desktop update notes.",
                    "--platform",
                    "darwin-aarch64",
                    "--output",
                    str(output),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(write_desktop_update_manifest(), 0)
            finally:
                sys.argv = old_argv

            manifest = __import__("json").loads(output.read_text(encoding="utf-8"))
            platform = manifest["platforms"]["darwin-aarch64"]
            self.assertEqual("0.1.13", manifest["version"])
            self.assertEqual("Desktop update notes.", manifest["notes"])
            self.assertEqual("trusted-signature", platform["signature"])
            self.assertEqual("https://example.test/releases/InferGrade%20Runner.app.tar.gz", platform["url"])
            self.assertRegex(manifest["pub_date"], r"Z$")

    def test_desktop_update_manifest_can_include_multiple_platform_artifacts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            mac_archive = root / "InferGrade Runner.app.tar.gz"
            mac_signature = root / "InferGrade Runner.app.tar.gz.sig"
            windows_archive = root / "InferGrade Runner_0.1.13_x64-setup.exe.zip"
            windows_signature = root / "InferGrade Runner_0.1.13_x64-setup.exe.zip.sig"
            output = root / "latest.json"
            mac_archive.write_bytes(b"mac archive")
            mac_signature.write_text("mac-signature\n", encoding="utf-8")
            windows_archive.write_bytes(b"windows archive")
            windows_signature.write_text("windows-signature\n", encoding="utf-8")

            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_update_manifest",
                    "--version",
                    "0.1.13",
                    "--base-url",
                    "https://example.test/releases",
                    "--notes",
                    "Desktop update notes.",
                    "--artifact",
                    f"darwin-aarch64={mac_archive}",
                    "--artifact",
                    f"windows-x86_64={windows_archive}",
                    "--output",
                    str(output),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(write_desktop_update_manifest(), 0)
            finally:
                sys.argv = old_argv

            manifest = __import__("json").loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(manifest["platforms"].keys()),
                ["darwin-aarch64", "windows-x86_64"],
            )
            self.assertEqual("mac-signature", manifest["platforms"]["darwin-aarch64"]["signature"])
            self.assertEqual("windows-signature", manifest["platforms"]["windows-x86_64"]["signature"])
            self.assertEqual(
                "https://example.test/releases/InferGrade%20Runner_0.1.13_x64-setup.exe.zip",
                manifest["platforms"]["windows-x86_64"]["url"],
            )

    def test_desktop_update_manifest_requires_exactly_one_archive(self):
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "bundle"
            bundle_dir.mkdir()
            output = Path(tmp) / "latest.json"
            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_update_manifest",
                    "--bundle-dir",
                    str(bundle_dir),
                    "--version",
                    "0.1.13",
                    "--base-url",
                    "https://example.test/releases",
                    "--output",
                    str(output),
                ]
                with self.assertRaises(SystemExit) as raised:
                    write_desktop_update_manifest()
            finally:
                sys.argv = old_argv

            self.assertIn("Expected exactly one updater .tar.gz archive", str(raised.exception))
            self.assertFalse(output.exists())

    def test_desktop_update_manifest_requires_signature(self):
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "bundle"
            bundle_dir.mkdir()
            (bundle_dir / "InferGrade.Runner.app.tar.gz").write_bytes(b"archive")
            output = Path(tmp) / "latest.json"
            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_update_manifest",
                    "--bundle-dir",
                    str(bundle_dir),
                    "--version",
                    "0.1.13",
                    "--base-url",
                    "https://example.test/releases",
                    "--output",
                    str(output),
                ]
                with self.assertRaises(SystemExit) as raised:
                    write_desktop_update_manifest()
            finally:
                sys.argv = old_argv

            self.assertIn("No signature file found", str(raised.exception))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
