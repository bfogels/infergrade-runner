import json
import tempfile
import unittest
from pathlib import Path

from infergrade.contracts import export_contract_bundle, load_contract_manifest, repo_root
from infergrade.releases import export_release_bundle, load_release_manifest


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
            for relative_path in exported_manifest.get("catalog_files", []):
                self.assertTrue((bundle_dir / relative_path).exists(), relative_path)
            for relative_path in exported_manifest["supporting_docs"]:
                self.assertTrue((bundle_dir / relative_path).exists(), relative_path)

    def test_repo_root_points_at_runner_repo(self):
        self.assertTrue((repo_root() / "schemas" / "contract_manifest.json").exists())

    def test_export_release_bundle_writes_manifest_and_artifact_checksums(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as output_dir:
            source_root = Path(source_dir)
            output_root = Path(output_dir)
            (source_root / "schemas" / "json").mkdir(parents=True)
            (source_root / "schemas" / "examples").mkdir(parents=True)
            (source_root / "docs").mkdir(parents=True)
            (source_root / "schemas" / "contract_manifest.json").write_text(
                json.dumps(
                    {
                        "contract_version": "1.2.3",
                        "publisher": "infergrade-runner",
                        "ontology_source": "schemas/json/model_ontology.schema.json",
                        "schema_files": ["schemas/json/model_ontology.schema.json"],
                        "example_files": ["schemas/examples/example.json"],
                        "catalog_files": ["schemas/capability_catalog.json"],
                        "supporting_docs": ["docs/contract_ownership.md"],
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "schemas" / "json" / "model_ontology.schema.json").write_text("{}", encoding="utf-8")
            (source_root / "schemas" / "examples" / "example.json").write_text("{}", encoding="utf-8")
            (source_root / "schemas" / "capability_catalog.json").write_text("{}", encoding="utf-8")
            (source_root / "docs" / "contract_ownership.md").write_text("# contract", encoding="utf-8")
            image_dir = source_root / "dist" / "images" / "1.2.3-alpha"
            image_dir.mkdir(parents=True)
            (image_dir / "infergrade-runner-core_1.2.3-alpha.tar").write_text("runner-image", encoding="utf-8")
            (image_dir / "infergrade-llama-cpp_1.2.3-alpha.tar").write_text("runtime-image", encoding="utf-8")
            (image_dir / "infergrade-mmlu-pro_1.2.3-alpha.tar").write_text("mmlu-image", encoding="utf-8")

            bundle_dir = export_release_bundle(
                output_dir=output_root,
                root=source_root,
                release_version="1.2.3-alpha",
            )

            manifest = load_release_manifest(bundle_dir=bundle_dir)
            self.assertEqual("1.2.3-alpha", manifest["release_version"])
            self.assertEqual("1.2.3", manifest["contract_version"])
            self.assertEqual("0.1.3", manifest["runner_version"])
            self.assertEqual("alpha", manifest["release_channel"])
            self.assertEqual(
                "infergrade-runner-core:1.2.3-alpha",
                manifest["golden_paths"]["local_listener_container"]["runner_image"],
            )
            self.assertTrue((bundle_dir / "contract" / "contract_manifest.json").exists())
            self.assertTrue((bundle_dir / "images" / "infergrade-runner-core_1.2.3-alpha.tar").exists())
            self.assertGreaterEqual(len(manifest["artifacts"]), 3)
            self.assertFalse((source_root / "dist" / "contracts").exists())
            runtime_refs = {item["image_name"]: item for item in manifest["runtime_images"]}
            capability_refs = {item["image_name"]: item for item in manifest["capability_images"]}
            self.assertEqual(
                "images/infergrade-runner-core_1.2.3-alpha.tar",
                runtime_refs["infergrade-runner-core"]["archive_path"],
            )
            self.assertEqual(
                "images/infergrade-mmlu-pro_1.2.3-alpha.tar",
                capability_refs["infergrade-mmlu-pro"]["archive_path"],
            )


if __name__ == "__main__":
    unittest.main()
