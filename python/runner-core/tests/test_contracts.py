import json
import tempfile
import unittest
from pathlib import Path

from infergrade.contracts import export_contract_bundle, load_contract_manifest, repo_root


class ContractExportTests(unittest.TestCase):
    def test_manifest_version_matches_runner_version(self):
        manifest = load_contract_manifest()
        self.assertEqual("0.1.0", manifest["contract_version"])
        self.assertEqual("infergrade-runner", manifest["publisher"])

    def test_export_contract_bundle_copies_declared_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bundle_dir = export_contract_bundle(output_dir=Path(tempdir))
            manifest_path = bundle_dir / "contract_manifest.json"
            self.assertTrue(manifest_path.exists())

            exported_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("contract_bundle_v1", exported_manifest["export_format"])
            self.assertEqual("infergrade-runner", exported_manifest["publisher"])

            for relative_path in exported_manifest["schema_files"]:
                self.assertTrue((bundle_dir / relative_path).exists(), relative_path)
            for relative_path in exported_manifest["example_files"]:
                self.assertTrue((bundle_dir / relative_path).exists(), relative_path)
            for relative_path in exported_manifest["supporting_docs"]:
                self.assertTrue((bundle_dir / relative_path).exists(), relative_path)

    def test_repo_root_points_at_runner_repo(self):
        self.assertTrue((repo_root() / "schemas" / "contract_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
