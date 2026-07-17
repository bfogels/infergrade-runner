import contextlib
import io
import json
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from scripts.sync_versions import sync_versions
from scripts.check_public_release_readiness import main as check_public_release_readiness
from scripts.verify_desktop_release_artifacts import main as verify_desktop_release_artifacts
from scripts.verify_desktop_update_endpoint import verify_manifest as verify_desktop_update_manifest_endpoint
from scripts.write_desktop_release_checksums import main as write_desktop_release_checksums
from scripts.write_desktop_update_manifest import main as write_desktop_update_manifest


ROOT = Path(__file__).resolve().parents[3]


class ReleaseCiTests(unittest.TestCase):
    def test_desktop_release_workflow_verifies_public_updater_reachability(self):
        workflow = (ROOT / ".github" / "workflows" / "desktop-runner-release.yml").read_text(encoding="utf-8")

        self.assertIn("Verify anonymous updater access", workflow)
        self.assertIn("verify_desktop_update_endpoint.py", workflow)
        self.assertIn('--expected-version "$DESKTOP_VERSION"', workflow)

    def test_desktop_update_endpoint_requires_anonymous_manifest_and_archive_access(self):
        class Response:
            status = 200

            def __init__(self, body=b""):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size=-1):
                return self.body if size is None or size < 0 else self.body[:size]

        requests = []

        def opener(request, timeout=0):
            requests.append((request.full_url, request.get_method(), request.headers, timeout))
            if request.headers.get("Range"):
                return Response()
            return Response(
                json.dumps(
                    {
                        "version": "0.3.36",
                        "platforms": {
                            "darwin-aarch64": {
                                "signature": "signed",
                                "url": "https://downloads.example.test/InferGrade.Runner.app.tar.gz",
                            }
                        },
                    }
                ).encode("utf-8")
            )

        manifest = verify_desktop_update_manifest_endpoint(
            "https://downloads.example.test/latest.json", "0.3.36", opener=opener, sleeper=lambda _delay: None
        )

        self.assertEqual(manifest["version"], "0.3.36")
        self.assertEqual([request[1] for request in requests], ["GET", "GET"])
        self.assertEqual(requests[1][2].get("Range"), "bytes=0-0")
        self.assertTrue(all("Authorization" not in request[2] for request in requests))

    def test_desktop_update_endpoint_rejects_version_drift(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"version": "0.3.35", "platforms": {"darwin-aarch64": {}}}).encode("utf-8")

        with self.assertRaises(SystemExit) as raised:
            verify_desktop_update_manifest_endpoint(
                "https://downloads.example.test/latest.json", "0.3.36", opener=lambda *_args, **_kwargs: Response()
            )
        self.assertIn("version mismatch", str(raised.exception))

    def test_desktop_update_endpoint_retries_archive_propagation(self):
        class Response:
            status = 200

            def __init__(self, body=b""):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size=-1):
                return self.body if size is None or size < 0 else self.body[:size]

        artifact_attempts = 0
        delays = []

        def opener(request, timeout=0):
            nonlocal artifact_attempts
            if request.headers.get("Range"):
                artifact_attempts += 1
                if artifact_attempts == 1:
                    raise OSError("release asset is still propagating")
                return Response(b"a")
            return Response(json.dumps({
                "version": "0.3.36",
                "platforms": {"darwin-aarch64": {
                    "signature": "signed",
                    "url": "https://downloads.example.test/InferGrade.Runner.app.tar.gz",
                }},
            }).encode("utf-8"))

        verify_desktop_update_manifest_endpoint(
            "https://downloads.example.test/latest.json",
            "0.3.36",
            opener=opener,
            attempts=2,
            sleeper=delays.append,
        )

        self.assertEqual(artifact_attempts, 2)
        self.assertEqual(delays, [1])

    def test_release_bundle_workflow_runs_only_for_version_tags_or_manual_dispatch(self):
        workflow = (ROOT / ".github" / "workflows" / "release-bundle.yml").read_text(encoding="utf-8")

        self.assertIn('tags:\n      - "v*"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("branches:", workflow)
        self.assertIn("./scripts/build_release_bundle.sh", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertIn("infergrade-runner-release-${{ steps.release_bundle.outputs.release_version }}", workflow)
        self.assertIn("retention-days: 7", workflow)

    def test_release_bundle_script_defaults_to_version(self):
        script = (ROOT / "scripts" / "build_release_bundle.sh").read_text(encoding="utf-8")

        self.assertIn('VERSION_TAG="${INFERGRADE_RELEASE_VERSION:-$(<"${ROOT_DIR}/VERSION")}"', script)
        self.assertIn("python3 ./scripts/check_versions.py", script)
        self.assertIn('python3 ./scripts/export_release_bundle.py --release-version "${VERSION_TAG}"', script)
        self.assertNotIn("0.1.0-preview", script)

    def test_release_image_scripts_default_to_version(self):
        for relative_path in ("scripts/build_release_images.sh", "scripts/export_release_images.sh"):
            script = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('VERSION_TAG="${INFERGRADE_IMAGE_TAG:-$(<"${ROOT_DIR}/VERSION")}"', script)
            self.assertNotIn("0.1.0-preview", script)
        build_script = (ROOT / "scripts" / "build_release_images.sh").read_text(encoding="utf-8")
        self.assertIn('-t "ghcr.io/bfogels/${name}:${VERSION_TAG}"', build_script)

    def test_release_image_verifier_is_anonymous_and_checks_every_image(self):
        script = (ROOT / "scripts" / "verify_release_images.sh").read_text(encoding="utf-8")
        self.assertIn('DOCKER_CONFIG_DIR="$(mktemp -d)"', script)
        self.assertIn('DOCKER_CONFIG="${DOCKER_CONFIG_DIR}" docker manifest inspect', script)
        for image in ("infergrade-runner-core", "infergrade-llama-cpp", "infergrade-ifeval", "infergrade-evalplus", "infergrade-mmlu-pro"):
            self.assertIn(image, script)

    def test_ci_checks_version_sync_before_running_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python3 ./scripts/sync_versions.py --check", workflow)
        self.assertIn("python3 ./scripts/check_versions.py", workflow)
        self.assertIn("python3 ./scripts/check_llama_cpp_runtime_policy.py", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertNotIn("git fetch origin main", workflow)

    def test_validation_workflows_scope_branches_and_cancel_superseded_runs(self):
        for filename in ("ci.yml", "secret-scan.yml"):
            workflow = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
            self.assertIn("push:\n    branches:\n      - main\n      - develop", workflow)
            self.assertIn("pull_request:\n    branches:\n      - main\n      - develop", workflow)
            self.assertIn("github.event.pull_request.number || github.ref", workflow)
            self.assertIn("cancel-in-progress: true", workflow)
            self.assertIn("timeout-minutes:", workflow)

    def test_workflow_actions_are_commit_pinned_and_validation_checkouts_drop_credentials(self):
        workflow_paths = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        for path in workflow_paths:
            workflow = path.read_text(encoding="utf-8")
            for line in workflow.splitlines():
                if "uses:" not in line:
                    continue
                self.assertRegex(
                    line,
                    r"uses:\s+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}\s+#\s+\S+",
                    msg=f"unpinned action in {path.name}: {line.strip()}",
                )
        for filename in ("ci.yml", "secret-scan.yml"):
            workflow = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
            self.assertEqual(workflow.count("persist-credentials: false"), workflow.count("actions/checkout@"))

    def test_llama_cpp_intake_is_read_only_advisory_automation(self):
        workflow = (ROOT / ".github" / "workflows" / "llama-cpp-runtime-intake.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('cron: "17 9 * * *"', workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("repos/ggml-org/llama.cpp/releases/latest", workflow)
        self.assertIn("scripts/check_llama_cpp_runtime_policy.py", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("issues: write", workflow)

    def test_publish_container_workflow_defaults_to_version_file_at_runtime(self):
        workflow = (ROOT / ".github" / "workflows" / "publish-containers.yml").read_text(encoding="utf-8")

        self.assertIn('default: ""', workflow)
        self.assertIn('image_tag="$(cat VERSION)"', workflow)
        self.assertNotIn("0.1.31-preview", workflow)

    def test_desktop_app_uses_package_metadata_for_browser_version_fallback(self):
        js = (ROOT / "apps" / "desktop-runner" / "src" / "main.js").read_text(encoding="utf-8")
        html = (ROOT / "apps" / "desktop-runner" / "index.html").read_text(encoding="utf-8")

        self.assertIn('import packageInfo from "../package.json"', js)
        self.assertIn("const APP_VERSION_FALLBACK = packageInfo.version;", js)
        self.assertNotIn('APP_VERSION_FALLBACK = "0.1.', js)
        self.assertIn("<span class=\"version-chip\" data-app-version>checking...</span>", html)
        self.assertNotIn("data-app-version>0.1.", html)

    def test_sync_versions_updates_required_manifest_copies_from_version_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / "python/runner-core",
                root / "python/runner-core/src/infergrade",
                root / "apps/desktop-runner/src-tauri",
                root / "apps/runner-cli",
                root / "crates/runner-engine",
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
            (root / "apps/runner-cli/Cargo.toml").write_text(
                '[package]\nname = "infergrade-runner-cli"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "crates/runner-engine/Cargo.toml").write_text(
                '[package]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.lock").write_text(
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n'
                '[[package]]\nname = "schannel"\nversion = "0.1.29"\n',
                encoding="utf-8",
            )
            (root / "Cargo.lock").write_text(
                '[[package]]\nname = "infergrade-runner-cli"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n'
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
            self.assertIn('version = "1.2.3"', (root / "apps/runner-cli/Cargo.toml").read_text())
            self.assertIn('version = "1.2.3"', (root / "crates/runner-engine/Cargo.toml").read_text())
            cargo_lock = (root / "apps/desktop-runner/src-tauri/Cargo.lock").read_text()
            self.assertIn('name = "infergrade_desktop_runner"\nversion = "1.2.3"', cargo_lock)
            self.assertIn('name = "infergrade_runner_engine"\nversion = "1.2.3"', cargo_lock)
            self.assertIn('name = "schannel"\nversion = "0.1.29"', cargo_lock)
            workspace_cargo_lock = (root / "Cargo.lock").read_text()
            self.assertIn('name = "infergrade-runner-cli"\nversion = "1.2.3"', workspace_cargo_lock)
            self.assertIn('name = "infergrade_desktop_runner"\nversion = "1.2.3"', workspace_cargo_lock)
            self.assertIn('name = "infergrade_runner_engine"\nversion = "1.2.3"', workspace_cargo_lock)
            self.assertIn('name = "schannel"\nversion = "0.1.29"', workspace_cargo_lock)

    def test_sync_versions_fails_instead_of_rewriting_dependency_lock_versions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / "python/runner-core",
                root / "python/runner-core/src/infergrade",
                root / "apps/desktop-runner/src-tauri",
                root / "apps/runner-cli",
                root / "crates/runner-engine",
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
            (root / "apps/runner-cli/Cargo.toml").write_text(
                '[package]\nname = "infergrade-runner-cli"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "crates/runner-engine/Cargo.toml").write_text(
                '[package]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.lock").write_text(
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "Cargo.lock").write_text(
                '[[package]]\nname = "infergrade-runner-cli"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n',
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
                root / "apps/runner-cli",
                root / "crates/runner-engine",
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
            (root / "apps/runner-cli/Cargo.toml").write_text(
                '[package]\nname = "infergrade-runner-cli"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "crates/runner-engine/Cargo.toml").write_text(
                '[package]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "apps/desktop-runner/src-tauri/Cargo.lock").write_text(
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )
            (root / "Cargo.lock").write_text(
                '[[package]]\nname = "infergrade-runner-cli"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_desktop_runner"\nversion = "0.0.1"\n'
                '[[package]]\nname = "infergrade_runner_engine"\nversion = "0.0.1"\n',
                encoding="utf-8",
            )

            changed = sync_versions(root, dry_run=True)

            self.assertIn("python/runner-core/pyproject.toml", changed)
            self.assertIn('version = "0.0.1"', (root / "python/runner-core/pyproject.toml").read_text())

    def test_desktop_release_workflow_publishes_latest_dmg_only_when_dispatched(self):
        workflow = (ROOT / ".github" / "workflows" / "desktop-runner-release.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertIn("group: desktop-runner-release", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
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

        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("macos-preview:\n    name: Build and publish macOS desktop app\n    runs-on: macos-latest", workflow)
        self.assertIn("macos-preview:", workflow)
        self.assertIn("permissions:\n      contents: write", workflow)
        self.assertIn("windows-package-smoke:", workflow)
        self.assertIn("linux-package-smoke:", workflow)
        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn("runs-on: ubuntu-22.04", workflow)
        self.assertIn("windows-package-smoke:\n    name: Build Windows desktop packages\n    runs-on: windows-latest", workflow)
        self.assertIn("linux-package-smoke:\n    name: Build Linux desktop packages\n    runs-on: ubuntu-22.04", workflow)
        self.assertIn("npm run build:windows", workflow)
        self.assertIn("npm run build:linux", workflow)
        self.assertIn("libwebkit2gtk-4.1-dev", workflow)
        self.assertIn("libayatana-appindicator3-dev", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertEqual(workflow.count("retention-days: 7"), 2)
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

    def test_local_desktop_dmg_smoke_script_records_release_evidence(self):
        script = (ROOT / "scripts" / "smoke_desktop_dmg.sh").read_text(encoding="utf-8")

        self.assertIn("hdiutil attach", script)
        self.assertIn("codesign --verify --deep --strict --verbose=2", script)
        self.assertIn("env -i HOME=\"$HOME\" PATH='/usr/bin:/bin'", script)
        self.assertIn("infergrade-sidecar", script)
        self.assertIn("infergrade_desktop_runner", script)
        self.assertIn("desktop_dmg_smoke=pass", script)
        self.assertIn("desktop_dmg_sha256=", script)
        self.assertIn("desktop_dmg_sidecar_version=", script)
        self.assertIn("desktop_dmg_notarization=not_checked_by_local_smoke", script)
        self.assertIn("does not\nreplace Developer ID signing", script)

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

    def test_desktop_release_artifact_verifier_checks_checksums_and_updater_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dmg = root / "InferGrade Runner_0.2.5_aarch64.dmg"
            archive = root / "InferGrade Runner.app.tar.gz"
            signature = root / "InferGrade Runner.app.tar.gz.sig"
            manifest = root / "infergrade-runner-desktop-latest.json"
            checksums = root / "SHA256SUMS"
            dmg.write_bytes(b"dmg")
            archive.write_bytes(b"archive")
            signature.write_text("trusted-signature\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.2.5",
                        "platforms": {
                            "darwin-aarch64": {
                                "signature": "trusted-signature",
                                "url": "https://example.test/releases/InferGrade%20Runner.app.tar.gz",
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            old_argv = sys.argv
            try:
                sys.argv = [
                    "write_desktop_release_checksums",
                    "--output",
                    str(checksums),
                    str(dmg),
                    str(archive),
                    str(signature),
                    str(manifest),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(write_desktop_release_checksums(), 0)
                sys.argv = [
                    "verify_desktop_release_artifacts",
                    "--directory",
                    str(root),
                    "--require-dmg",
                    "--require-updater",
                ]
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(verify_desktop_release_artifacts(), 0)
            finally:
                sys.argv = old_argv

            output = stdout.getvalue()
            self.assertIn("desktop_release_artifacts_verified=4", output)
            self.assertIn("desktop_release_notarization=not_checked_by_artifact_manifest", output)

    def test_desktop_release_artifact_verifier_rejects_bad_checksums_and_missing_signatures(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dmg = root / "InferGrade Runner_0.2.5_aarch64.dmg"
            archive = root / "InferGrade Runner.app.tar.gz"
            manifest = root / "infergrade-runner-desktop-latest.json"
            checksums = root / "SHA256SUMS"
            dmg.write_bytes(b"dmg")
            archive.write_bytes(b"archive")
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.2.5",
                        "platforms": {
                            "darwin-aarch64": {
                                "signature": "trusted-signature",
                                "url": "https://example.test/releases/InferGrade%20Runner.app.tar.gz",
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            checksums.write_text("%s  %s\n" % ("0" * 64, dmg.name), encoding="utf-8")

            old_argv = sys.argv
            try:
                sys.argv = [
                    "verify_desktop_release_artifacts",
                    "--directory",
                    str(root),
                    "--require-dmg",
                ]
                with self.assertRaises(SystemExit) as raised:
                    verify_desktop_release_artifacts()
                self.assertIn("Checksum mismatch", str(raised.exception))

                checksums.write_text(
                    "%s  %s\n%s  %s\n%s  %s\n"
                    % (
                        __import__("hashlib").sha256(dmg.read_bytes()).hexdigest(),
                        dmg.name,
                        __import__("hashlib").sha256(archive.read_bytes()).hexdigest(),
                        archive.name,
                        __import__("hashlib").sha256(manifest.read_bytes()).hexdigest(),
                        manifest.name,
                    ),
                    encoding="utf-8",
                )
                sys.argv = [
                    "verify_desktop_release_artifacts",
                    "--directory",
                    str(root),
                    "--require-updater",
                ]
                with self.assertRaises(SystemExit) as raised:
                    verify_desktop_release_artifacts()
                self.assertIn("Updater signature artifact is missing", str(raised.exception))
            finally:
                sys.argv = old_argv

    def test_desktop_release_artifact_verifier_rejects_signature_mismatch_and_unchecksummed_updater_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dmg = root / "InferGrade Runner_0.2.5_aarch64.dmg"
            archive = root / "InferGrade Runner.app.tar.gz"
            signature = root / "InferGrade Runner.app.tar.gz.sig"
            manifest = root / "infergrade-runner-desktop-latest.json"
            checksums = root / "SHA256SUMS"
            dmg.write_bytes(b"dmg")
            archive.write_bytes(b"archive")
            signature.write_text("actual-signature\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.2.5",
                        "platforms": {
                            "darwin-aarch64": {
                                "signature": "manifest-signature",
                                "url": "https://example.test/releases/InferGrade%20Runner.app.tar.gz",
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            old_argv = sys.argv
            try:
                checksums.write_text(
                    "%s  %s\n%s  %s\n%s  %s\n%s  %s\n"
                    % (
                        __import__("hashlib").sha256(dmg.read_bytes()).hexdigest(),
                        dmg.name,
                        __import__("hashlib").sha256(archive.read_bytes()).hexdigest(),
                        archive.name,
                        __import__("hashlib").sha256(signature.read_bytes()).hexdigest(),
                        signature.name,
                        __import__("hashlib").sha256(manifest.read_bytes()).hexdigest(),
                        manifest.name,
                    ),
                    encoding="utf-8",
                )
                sys.argv = [
                    "verify_desktop_release_artifacts",
                    "--directory",
                    str(root),
                    "--require-updater",
                ]
                with self.assertRaises(SystemExit) as raised:
                    verify_desktop_release_artifacts()
                self.assertIn("signature does not match", str(raised.exception))

                manifest.write_text(
                    json.dumps(
                        {
                            "version": "0.2.5",
                            "platforms": {
                                "darwin-aarch64": {
                                    "signature": "actual-signature",
                                    "url": "https://example.test/releases/InferGrade%20Runner.app.tar.gz",
                                }
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                checksums.write_text(
                    "%s  %s\n%s  %s\n"
                    % (
                        __import__("hashlib").sha256(dmg.read_bytes()).hexdigest(),
                        dmg.name,
                        __import__("hashlib").sha256(manifest.read_bytes()).hexdigest(),
                        manifest.name,
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(SystemExit) as raised:
                    verify_desktop_release_artifacts()
                self.assertIn("not covered by SHA256SUMS", str(raised.exception))
            finally:
                sys.argv = old_argv

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

    def test_public_release_readiness_reports_local_checks_and_manual_gates(self):
        old_argv = sys.argv
        try:
            sys.argv = ["check_public_release_readiness", "--root", str(ROOT)]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(check_public_release_readiness(), 0)
        finally:
            sys.argv = old_argv

        output = stdout.getvalue()
        self.assertIn("public_release_readiness=manual_required", output)
        self.assertIn("release_evidence_scope=local_repository_checks_only", output)
        self.assertIn("release_signing_notarization=manual_github_release_environment_gate", output)
        self.assertIn("pass\tgit_repository_state\t", output)
        self.assertIn("pass\trequired_files\t", output)
        self.assertIn("pass\tdesktop_release_workflow\t", output)
        self.assertIn("pass\tsecret_filename_scan\t", output)
        self.assertIn("manual\tgithub_settings\t", output)
        self.assertIn("manual\tsigning_credentials\t", output)
        self.assertNotIn("release_signing_notarization=pass", output)

    def test_public_release_readiness_json_preserves_manual_state(self):
        old_argv = sys.argv
        try:
            sys.argv = ["check_public_release_readiness", "--root", str(ROOT), "--json"]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(check_public_release_readiness(), 0)
        finally:
            sys.argv = old_argv

        payload = json.loads(stdout.getvalue())
        self.assertEqual("manual_required", payload["status"])
        self.assertEqual("local_repository_checks_only", payload["scope"])
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertEqual("pass", checks["git_repository_state"]["status"])
        self.assertEqual("manual", checks["github_settings"]["status"])
        self.assertEqual("manual", checks["signing_credentials"]["status"])
        self.assertEqual("pass", checks["desktop_release_workflow"]["status"])

    def test_public_release_readiness_fails_for_suspicious_local_secret_filenames(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.2.5\n", encoding="utf-8")
            (root / "deploy.key").write_text("not a real secret\n", encoding="utf-8")

            old_argv = sys.argv
            try:
                sys.argv = ["check_public_release_readiness", "--root", str(root)]
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(check_public_release_readiness(), 1)
            finally:
                sys.argv = old_argv

            output = stdout.getvalue()
            self.assertIn("public_release_readiness=fail", output)
            self.assertIn("fail\tgit_repository_state\t", output)
            self.assertIn("fail\tsecret_filename_scan\t", output)
            self.assertIn("deploy.key", output)

    def test_public_release_readiness_fails_for_dirty_git_worktree(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.check_call(["git", "init"], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            (root / "VERSION").write_text("0.2.5\n", encoding="utf-8")
            subprocess.check_call(["git", "add", "VERSION"], cwd=root)
            subprocess.check_call(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            (root / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

            old_argv = sys.argv
            try:
                sys.argv = ["check_public_release_readiness", "--root", str(root)]
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(check_public_release_readiness(), 1)
            finally:
                sys.argv = old_argv

            output = stdout.getvalue()
            self.assertIn("public_release_readiness=fail", output)
            self.assertIn("fail\tgit_repository_state\tworktree is not clean", output)
            self.assertIn("dirty.txt", output)


if __name__ == "__main__":
    unittest.main()
