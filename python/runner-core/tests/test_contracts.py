import json
import tempfile
import unittest
from pathlib import Path

from infergrade import __version__
from infergrade.contracts import export_contract_bundle, load_contract_manifest, repo_root
from infergrade.cuda import windows_cuda_preflight
from infergrade.releases import export_release_bundle, load_release_manifest


def _matches_schema_type(value, schema_type):
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    for item in types:
        if item == "null" and value is None:
            return True
        if item == "object" and isinstance(value, dict):
            return True
        if item == "array" and isinstance(value, list):
            return True
        if item == "string" and isinstance(value, str):
            return True
        if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if item == "boolean" and isinstance(value, bool):
            return True
    return False


def _validate_schema_subset(value, schema, path="$"):
    if "const" in schema and value != schema["const"]:
        raise AssertionError("%s expected const %r, got %r" % (path, schema["const"], value))
    if "enum" in schema and value not in schema["enum"]:
        raise AssertionError("%s expected one of %r, got %r" % (path, schema["enum"], value))
    if "type" in schema and not _matches_schema_type(value, schema["type"]):
        raise AssertionError("%s expected type %r, got %r" % (path, schema["type"], type(value).__name__))
    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        raise AssertionError("%s expected minLength %r" % (path, schema["minLength"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema and value < schema["minimum"]:
        raise AssertionError("%s expected minimum %r" % (path, schema["minimum"]))
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                raise AssertionError("%s missing required key %s" % (path, key))
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise AssertionError("%s has unexpected keys %r" % (path, extra))
        for key, item in value.items():
            if key in properties:
                _validate_schema_subset(item, properties[key], "%s.%s" % (path, key))
    if isinstance(value, list):
        if schema.get("uniqueItems") and len(value) != len({json.dumps(item, sort_keys=True) for item in value}):
            raise AssertionError("%s expected unique items" % path)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate_schema_subset(item, item_schema, "%s[%d]" % (path, index))


class ContractExportTests(unittest.TestCase):
    def test_contract_declares_artifact_memory_fit_policy_schema_and_docs(self):
        manifest = load_contract_manifest()
        self.assertIn("schemas/json/artifact_memory_fit.schema.json", manifest["schema_files"])
        self.assertIn("schemas/json/artifact_memory_fit_policy.schema.json", manifest["schema_files"])
        self.assertIn("schemas/policies/artifact_memory_fit_policy.v1.json", manifest["policy_files"])
        self.assertNotIn("schemas/policies/artifact_memory_fit_policy.v1.json", manifest["catalog_files"])
        self.assertIn("docs/artifact_memory_fit_policy.md", manifest["supporting_docs"])

        policy = json.loads(
            (repo_root() / "schemas" / "policies" / "artifact_memory_fit_policy.v1.json").read_text(encoding="utf-8")
        )
        schema = json.loads(
            (repo_root() / "schemas" / "json" / "artifact_memory_fit.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policy["policy_id"], schema["properties"]["policy_id"]["const"])
        self.assertEqual(policy["estimator_version"], schema["properties"]["estimator_version"]["const"])
        self.assertEqual(policy["context_buckets_tokens"], [2048, 8192, 32768])
        self.assertEqual(schema["properties"]["claim_boundary"]["properties"]["fit_verdict"]["const"], "not_evaluated")
        self.assertFalse(schema["properties"]["claim_boundary"]["properties"]["guaranteed_bounds"]["const"])

    def test_result_record_contract_declares_versioned_memory_fit_bounds(self):
        schema = json.loads(
            (repo_root() / "schemas" / "json" / "result_record.schema.json").read_text(encoding="utf-8")
        )
        memory_fit = schema["properties"]["deployment"]["properties"]["memory_fit"]
        self.assertEqual(memory_fit["properties"]["current_context_status"]["enum"], ["runtime_reported", "unknown"])
        self.assertEqual(memory_fit["properties"]["current_context"]["oneOf"][0]["$ref"], "#/$defs/memoryFitEstimate")
        self.assertEqual(memory_fit["properties"]["current_context"]["oneOf"][1]["type"], "null")
        estimate = schema["$defs"]["memoryFitEstimate"]
        self.assertEqual(estimate["properties"]["estimator_version"]["const"], "memory_fit_v1")
        self.assertEqual(estimate["properties"]["status"]["enum"], ["estimated", "unknown"])
        self.assertEqual(estimate["properties"]["fit_verdict"]["const"], "not_evaluated")
        self.assertIn("runtime_reported", schema["$defs"]["memoryComponent"]["properties"]["source"]["enum"])

    def test_manifest_declares_versioned_contract(self):
        manifest = load_contract_manifest()
        self.assertEqual(manifest["contract_version"], "0.3.23")
        self.assertEqual("infergrade-runner", manifest["publisher"])

    def test_run_request_contract_accepts_authorized_artifact_download_size(self):
        schema = json.loads(
            (repo_root() / "schemas" / "json" / "run_request.schema.json").read_text(encoding="utf-8")
        )
        request = {
            "spec_version": "0.1-draft",
            "run": {
                "model": "example/model",
                "backend": "llama.cpp",
                "tier": "canary",
            },
            "artifacts": {
                "quantized_weights": {
                    "uri": "hf://example/model-GGUF/model.gguf",
                    "revision": "0123456789abcdef",
                    "sha256": "a" * 64,
                    "download_size_bytes": 123456,
                }
            },
        }
        _validate_schema_subset(request, schema)

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
            for relative_path in exported_manifest.get("policy_files", []):
                self.assertTrue((bundle_dir / relative_path).exists(), relative_path)
            for relative_path in exported_manifest["supporting_docs"]:
                self.assertTrue((bundle_dir / relative_path).exists(), relative_path)

    def test_contract_bundle_declares_runtime_selector_schema_and_examples(self):
        manifest = load_contract_manifest()
        self.assertIn("schemas/json/runtime_selector.schema.json", manifest["schema_files"])
        self.assertIn("schemas/examples/runtime_selector.macos_metal_managed.json", manifest["example_files"])
        self.assertIn("schemas/examples/runtime_selector.windows_cuda_preview.json", manifest["example_files"])

        selector_schema = json.loads(
            (repo_root() / "schemas" / "json" / "runtime_selector.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual("0.3", selector_schema["properties"]["runtime_selector_version"]["const"])
        self.assertIn("cuda", selector_schema["properties"]["accelerator"]["properties"]["api"]["enum"])
        self.assertIn("driver", selector_schema["properties"])
        self.assertIn("minimum_required", selector_schema["properties"]["driver"]["properties"])
        self.assertIn("fingerprint", selector_schema["properties"]["binary"]["properties"])
        self.assertIn("technical_beta", selector_schema["properties"]["support"]["properties"]["tier"]["enum"])
        self.assertIn(
            "runtime_delivery_gate",
            selector_schema["properties"]["delivery"]["properties"],
        )

        cuda_example = json.loads(
            (repo_root() / "schemas" / "examples" / "runtime_selector.windows_cuda_preview.json").read_text(encoding="utf-8")
        )
        self.assertEqual("cuda", cuda_example["accelerator"]["api"])
        self.assertIn({"id": "cuda_version", "status": "passed", "observed": "12.5"}, cuda_example["compatibility"]["probes"])
        self.assertEqual("preview", cuda_example["support"]["tier"])
        self.assertEqual("blocked", cuda_example["delivery"]["runtime_delivery_gate"]["status"])
        self.assertTrue(cuda_example["delivery"]["runtime_delivery_gate"]["pinned_manifest_available"])
        self.assertTrue(cuda_example["delivery"]["runtime_delivery_gate"]["checksum_verification_available"])
        self.assertEqual(cuda_example["delivery"]["runtime_delivery_gate"]["candidate_release"]["tag"], "b9371")
        self.assertIn(
            "candidate_artifacts",
            selector_schema["properties"]["delivery"]["properties"]["runtime_delivery_gate"]["properties"],
        )
        self.assertIn(
            "candidate_review",
            selector_schema["properties"]["delivery"]["properties"]["runtime_delivery_gate"]["properties"],
        )
        self.assertEqual(cuda_example["delivery"]["runtime_delivery_gate"]["candidate_review"]["status"], "blocked")
        example_review_checks = {
            item["id"]: item
            for item in cuda_example["delivery"]["runtime_delivery_gate"]["candidate_review"]["checks"]
        }
        self.assertEqual(example_review_checks["asset_sha256_digests_pinned"]["status"], "recorded")
        self.assertEqual(example_review_checks["archive_contents_inspected"]["status"], "pending")
        self.assertIn(
            "candidate_runtime_not_validated",
            cuda_example["delivery"]["runtime_delivery_gate"]["reason_codes"],
        )
        self.assertFalse(cuda_example["fallback"]["allowed"])
        self.assertIn("full_loop_not_proven", cuda_example["compatibility"]["reason_codes"])
        _validate_schema_subset(cuda_example, selector_schema)

    def test_contract_declares_exact_runtime_receipts(self):
        manifest = load_contract_manifest()
        self.assertIn("schemas/json/runtime_receipt.schema.json", manifest["schema_files"])
        self.assertIn("schemas/json/runtime_receipt_artifact.schema.json", manifest["schema_files"])
        self.assertIn("schemas/examples/runtime_receipt.example.json", manifest["example_files"])
        result_schema = json.loads(
            (repo_root() / "schemas" / "json" / "result_record.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            result_schema["properties"]["execution"]["properties"]["runtime_receipt"]["$ref"],
            "runtime_receipt.schema.json",
        )
        receipt_schema = json.loads(
            (repo_root() / "schemas" / "json" / "runtime_receipt.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt_schema["properties"]["receipt_version"]["const"],
            "infergrade_runtime_receipt_v1",
        )
        self.assertNotIn("files", receipt_schema["properties"])
        self.assertEqual(receipt_schema["properties"]["role_files"]["minItems"], 1)
        self.assertEqual(receipt_schema["properties"]["role_files"]["maxItems"], 3)
        self.assertIn(
            "source_assertion_id",
            receipt_schema["properties"]["provenance_evidence"]["oneOf"][0]["required"],
        )
        self.assertTrue(receipt_schema["allOf"])
        self.assertFalse(
            receipt_schema["properties"]["verification"]["properties"]
            ["silent_substitution_allowed"]["const"]
        )
        receipt_example = json.loads(
            (repo_root() / "schemas" / "examples" / "runtime_receipt.example.json").read_text(encoding="utf-8")
        )
        _validate_schema_subset(receipt_example, receipt_schema)
        artifact_schema = json.loads(
            (repo_root() / "schemas" / "json" / "runtime_receipt_artifact.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("files", artifact_schema["required"])
        self.assertEqual(artifact_schema["properties"]["files"]["maxItems"], 4096)

    def test_runtime_selector_schema_accepts_emitted_windows_cuda_preflight_selector(self):
        selector_schema = json.loads(
            (repo_root() / "schemas" / "json" / "runtime_selector.schema.json").read_text(encoding="utf-8")
        )
        preflight = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9, 12.5\n",
            platform_snapshot={"system": "Windows", "arch": "AMD64", "version": "11"},
            which=lambda _name: None,
        )

        _validate_schema_subset(preflight["selector"], selector_schema)
        self.assertEqual("missing_path", preflight["selector"]["binary"]["fingerprint"]["status"])

    def test_contract_bundle_includes_windows_cuda_beta_docs(self):
        manifest = load_contract_manifest()
        self.assertIn("docs/windows_nvidia_cuda_beta.md", manifest["supporting_docs"])

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
            image_dir = source_root / "dist" / "images" / "1.2.3-preview"
            image_dir.mkdir(parents=True)
            (image_dir / "infergrade-runner-core_1.2.3-preview.tar").write_text("runner-image", encoding="utf-8")
            (image_dir / "infergrade-llama-cpp_1.2.3-preview.tar").write_text("runtime-image", encoding="utf-8")
            (image_dir / "infergrade-mmlu-pro_1.2.3-preview.tar").write_text("mmlu-image", encoding="utf-8")

            bundle_dir = export_release_bundle(
                output_dir=output_root,
                root=source_root,
                release_version="1.2.3-preview",
            )

            manifest = load_release_manifest(bundle_dir=bundle_dir)
            self.assertEqual("1.2.3-preview", manifest["release_version"])
            self.assertEqual("1.2.3", manifest["contract_version"])
            self.assertEqual(__version__, manifest["runner_version"])
            self.assertEqual("preview", manifest["release_channel"])
            self.assertEqual(
                "ghcr.io/bfogels/infergrade-runner-core:1.2.3-preview",
                manifest["golden_paths"]["local_listener_container"]["runner_image"],
            )
            self.assertTrue((bundle_dir / "contract" / "contract_manifest.json").exists())
            self.assertTrue((bundle_dir / "images" / "infergrade-runner-core_1.2.3-preview.tar").exists())
            self.assertGreaterEqual(len(manifest["artifacts"]), 3)
            self.assertFalse((source_root / "dist" / "contracts").exists())
            runtime_refs = {item["image_name"]: item for item in manifest["runtime_images"]}
            capability_refs = {item["image_name"]: item for item in manifest["capability_images"]}
            self.assertTrue(all(item["image_ref"].startswith("ghcr.io/bfogels/") for item in manifest["runtime_images"] + manifest["capability_images"]))
            self.assertEqual(
                "images/infergrade-runner-core_1.2.3-preview.tar",
                runtime_refs["infergrade-runner-core"]["archive_path"],
            )
            self.assertEqual(
                "images/infergrade-mmlu-pro_1.2.3-preview.tar",
                capability_refs["infergrade-mmlu-pro"]["archive_path"],
            )


if __name__ == "__main__":
    unittest.main()
