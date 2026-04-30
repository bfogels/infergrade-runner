import unittest
from pathlib import Path


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

    def test_desktop_release_workflow_publishes_latest_dmg_on_main_push(self):
        workflow = (ROOT / ".github" / "workflows" / "desktop-runner-release.yml").read_text(encoding="utf-8")

        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("RELEASE_TAG: desktop-runner-latest", workflow)
        self.assertIn("./scripts/build_desktop_runner.sh --with-updater", workflow)
        self.assertIn("apps/desktop-runner/src-tauri/target/release/bundle/dmg/*.dmg", workflow)
        self.assertIn("gh release upload", workflow)

    def test_desktop_build_script_ignores_empty_apple_signing_env(self):
        script = (ROOT / "scripts" / "build_desktop_runner.sh").read_text(encoding="utf-8")

        self.assertIn("unset_if_empty APPLE_CERTIFICATE", script)
        self.assertIn("unset_if_empty APPLE_CERTIFICATE_PASSWORD", script)
        self.assertIn("unset_if_empty APPLE_ID", script)
        self.assertIn('MACOS_SIGNING_IDENTITY="-"', script)


if __name__ == "__main__":
    unittest.main()
