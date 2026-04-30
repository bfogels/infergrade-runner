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

    def test_release_bundle_script_defaults_to_version_alpha(self):
        script = (ROOT / "scripts" / "build_release_bundle.sh").read_text(encoding="utf-8")

        self.assertIn('VERSION_TAG="${INFERGRADE_RELEASE_VERSION:-$(<"${ROOT_DIR}/VERSION")-alpha}"', script)
        self.assertIn("python3 ./scripts/check_versions.py", script)
        self.assertIn('python3 ./scripts/export_release_bundle.py --release-version "${VERSION_TAG}"', script)
        self.assertNotIn("0.1.0-alpha", script)

    def test_alpha_image_scripts_default_to_version_alpha(self):
        for relative_path in ("scripts/build_alpha_images.sh", "scripts/export_alpha_images.sh"):
            script = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('VERSION_TAG="${INFERGRADE_IMAGE_TAG:-$(<"${ROOT_DIR}/VERSION")-alpha}"', script)
            self.assertNotIn("0.1.0-alpha", script)


if __name__ == "__main__":
    unittest.main()
