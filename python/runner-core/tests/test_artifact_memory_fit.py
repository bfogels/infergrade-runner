import json
import tempfile
import unittest
from pathlib import Path

from infergrade.artifact_memory_fit import (
    POLICY_ID,
    build_gguf_artifact_memory_fit,
    export_gguf_artifact_memory_fit,
    load_artifact_memory_fit_policy,
)


class ArtifactMemoryFitTests(unittest.TestCase):
    def setUp(self):
        self.architecture = {
            "layer_count": 32,
            "embedding_length": 4096,
            "attention_head_count": 32,
            "attention_head_count_kv": 8,
        }

    def test_policy_is_versioned_runner_owned_and_artifact_only(self):
        policy = load_artifact_memory_fit_policy()
        self.assertEqual(policy["policy_id"], POLICY_ID)
        self.assertEqual(policy["publisher"], "infergrade-runner")
        self.assertEqual(policy["artifact_format"], "gguf")
        self.assertEqual(policy["context_buckets_tokens"], [2048, 8192, 32768])
        self.assertEqual(
            policy["deployment_profile_context_buckets"],
            {"interactive_chat_v1": 2048, "batch_generation_v1": 8192, "long_context_v1": 32768},
        )
        self.assertEqual(
            policy["fit_thresholds"],
            {
                "ratio_basis": "estimate_range_high_bytes / available_capacity_bytes",
                "fits_max_inclusive": 0.80,
                "tight_min_exclusive": 0.80,
                "tight_max_inclusive": 1.00,
                "over_min_exclusive": 1.00,
            },
        )
        self.assertFalse(policy["fallback_network_policy"]["additional_metadata_fetch_required"])
        self.assertFalse(policy["claim_boundary"]["support_proof"])
        self.assertEqual(policy["claim_boundary"]["fit_verdict"], "not_evaluated")

    def test_builds_monotonic_2k_8k_32k_ranges_without_bounds_or_fit_claim(self):
        artifact = build_gguf_artifact_memory_fit(4 * 1024**3, self.architecture)
        self._assert_valid_artifact(artifact)
        estimates = [artifact["context_estimates"][str(tokens)] for tokens in (2048, 8192, 32768)]
        self.assertEqual([item["context_tokens"] for item in estimates], [2048, 8192, 32768])
        self.assertEqual(
            [item["components"]["kv_cache_estimate_bytes"] for item in estimates],
            [256 * 1024**2, 1024**3, 4 * 1024**3],
        )
        self.assertEqual(
            [item["estimate_range_high_bytes"] for item in estimates],
            sorted(item["estimate_range_high_bytes"] for item in estimates),
        )
        self.assertTrue(all(item["lower_bound_bytes"] is None for item in estimates))
        self.assertTrue(all(item["upper_bound_bytes"] is None for item in estimates))
        self.assertTrue(all(item["fit_verdict"] == "not_evaluated" for item in estimates))
        self.assertEqual(artifact["claim_boundary"]["memory_domain"], "unified_or_combined_memory")
        self.assertEqual(artifact["claim_boundary"]["offload_policy"], "unknown")
        self.assertFalse(artifact["claim_boundary"]["guaranteed_bounds"])
        self.assertFalse(artifact["source"]["runtime_measurements_used"])
        self.assertEqual(artifact["context_estimates"]["2048"]["method"], "architecture_formula")

    def test_artifact_size_only_fallback_emits_wide_monotonic_ranges_without_extra_source(self):
        artifact = build_gguf_artifact_memory_fit(4 * 1024**3)
        self._assert_valid_artifact(artifact)
        estimates = [artifact["context_estimates"][str(tokens)] for tokens in (2048, 8192, 32768)]
        self.assertIsNone(artifact["architecture_metadata"])
        self.assertEqual(artifact["source"]["architecture_metadata_source"], "unknown")
        self.assertTrue(all(item["method"] == "artifact_size_fallback_range" for item in estimates))
        self.assertTrue(all(item["source"] == "artifact_size_fallback_estimated" for item in estimates))
        self.assertTrue(all(item["components"]["kv_cache_estimate_bytes"] is None for item in estimates))
        self.assertEqual(
            [item["estimate_range_low_bytes"] for item in estimates],
            sorted(item["estimate_range_low_bytes"] for item in estimates),
        )
        self.assertEqual(
            [item["estimate_range_high_bytes"] for item in estimates],
            sorted(item["estimate_range_high_bytes"] for item in estimates),
        )
        self.assertTrue(all(item["upper_bound_bytes"] is None for item in estimates))
        self.assertFalse(artifact["claim_boundary"]["guaranteed_bounds"])

    def test_source_distinguishes_exact_size_observation_from_estimated_allocation(self):
        artifact = build_gguf_artifact_memory_fit(
            4 * 1024**3,
            self.architecture,
            artifact_size_source="repository_metadata",
        )
        self.assertEqual(artifact["source"]["artifact_size_source"], "repository_metadata")
        self.assertEqual(artifact["status"], "estimated")
        self.assertEqual(artifact["context_estimates"]["2048"]["source"], "architecture_formula_estimated")
        self.assertIn("runtime_overhead_uncalibrated_range", {item["id"] for item in artifact["assumptions"]})

    def test_export_writes_deterministic_versioned_json_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "nested" / "memory-fit.json"
            exported = export_gguf_artifact_memory_fit(output, 4 * 1024**3, self.architecture)
            payload = json.loads(exported.read_text(encoding="utf-8"))
            self.assertEqual(exported, output)
            self.assertEqual(payload["artifact_version"], "1.0")
            self.assertEqual(payload["policy_id"], POLICY_ID)
            self.assertEqual(sorted(payload["context_estimates"]), ["2048", "32768", "8192"])

    def test_rejects_missing_or_non_integer_artifact_facts(self):
        for invalid in (None, 0, -1, True, 1.5, "1024"):
            with self.assertRaises(ValueError):
                build_gguf_artifact_memory_fit(invalid, self.architecture)
        for field in self.architecture:
            invalid_architecture = dict(self.architecture)
            invalid_architecture[field] = None
            with self.assertRaises(ValueError):
                build_gguf_artifact_memory_fit(1024, invalid_architecture)

    def test_formula_accepts_declared_architecture_sources_and_rejects_malformed_provided_metadata(self):
        for source in ("gguf_metadata", "repository_config"):
            artifact = build_gguf_artifact_memory_fit(
                1024, self.architecture, architecture_metadata_source=source
            )
            self.assertEqual(artifact["source"]["architecture_metadata_source"], source)
            self.assertEqual(artifact["context_estimates"]["2048"]["method"], "architecture_formula")
        for malformed in ({}, "not-an-object", {**self.architecture, "layer_count": 1.0}):
            with self.assertRaises(ValueError):
                build_gguf_artifact_memory_fit(1024, malformed)
        with self.assertRaises(ValueError):
            build_gguf_artifact_memory_fit(1024, None, architecture_metadata_source="repository_config")

    def test_rejects_unsupported_size_source_and_attention_geometry(self):
        with self.assertRaises(ValueError):
            build_gguf_artifact_memory_fit(1024, self.architecture, artifact_size_source="guessed")
        invalid_architecture = {**self.architecture, "embedding_length": 4095}
        with self.assertRaises(ValueError):
            build_gguf_artifact_memory_fit(1024, invalid_architecture)
        with self.assertRaises(ValueError):
            build_gguf_artifact_memory_fit(
                1024, self.architecture, architecture_metadata_source="guessed"
            )
        for invalid_architecture in (
            {**self.architecture, "attention_head_count": 30},
            {**self.architecture, "attention_head_count": 32, "attention_head_count_kv": 6},
            {**self.architecture, "attention_head_count": 8, "attention_head_count_kv": 16},
        ):
            with self.assertRaises(ValueError):
                build_gguf_artifact_memory_fit(1024, invalid_architecture)

    def test_policy_conforms_to_manifested_policy_schema(self):
        root = Path(__file__).resolve().parents[3]
        policy = json.loads((root / "schemas" / "policies" / "artifact_memory_fit_policy.v1.json").read_text())
        schema = json.loads((root / "schemas" / "json" / "artifact_memory_fit_policy.schema.json").read_text())
        _validate_json_schema(policy, schema, schema)

    def test_rejects_non_monotonic_low_and_high_fallback_policy(self):
        policy = load_artifact_memory_fit_policy()
        policy["fallback_context_ranges"]["8192"]["low_floor_bytes"] = 1
        policy["fallback_context_ranges"]["8192"]["low_ratio_of_artifact_size"] = 0.001
        with self.assertRaises(ValueError):
            build_gguf_artifact_memory_fit(4 * 1024**3, policy=policy)

    def _assert_valid_artifact(self, artifact):
        root = Path(__file__).resolve().parents[3]
        schema = json.loads((root / "schemas" / "json" / "artifact_memory_fit.schema.json").read_text())
        _validate_json_schema(artifact, schema, schema)


def _validate_json_schema(value, schema, root_schema, path="$"):
    """Validate the stdlib-only JSON Schema subset used by these artifacts."""
    if "$ref" in schema:
        target = root_schema
        reference = schema["$ref"]
        for part in (reference[2:] if reference.startswith("#/") else reference).split("/"):
            target = target[part]
        return _validate_json_schema(value, target, root_schema, path)
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                _validate_json_schema(value, option, root_schema, path)
                matches += 1
            except AssertionError:
                pass
        if matches != 1:
            raise AssertionError("%s expected exactly one schema match, got %d" % (path, matches))
        return
    if "const" in schema and value != schema["const"]:
        raise AssertionError("%s expected const %r" % (path, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        raise AssertionError("%s expected enum member" % path)
    expected_types = schema.get("type")
    if expected_types:
        types = expected_types if isinstance(expected_types, list) else [expected_types]
        matches_type = any(
            (item == "null" and value is None)
            or (item == "object" and isinstance(value, dict))
            or (item == "array" and isinstance(value, list))
            or (item == "string" and isinstance(value, str))
            or (item == "boolean" and isinstance(value, bool))
            or (item == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
            for item in types
        )
        if not matches_type:
            raise AssertionError("%s has wrong type" % path)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema:
        if value < schema["minimum"]:
            raise AssertionError("%s is below minimum" % path)
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise AssertionError("%s is shorter than minLength" % path)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                raise AssertionError("%s missing %s" % (path, name))
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise AssertionError("%s has unexpected properties %r" % (path, sorted(extras)))
        for name, item in value.items():
            if name in properties:
                _validate_json_schema(item, properties[name], root_schema, "%s.%s" % (path, name))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise AssertionError("%s has too few items" % path)
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise AssertionError("%s has duplicate items" % path)
        if schema.get("items"):
            for index, item in enumerate(value):
                _validate_json_schema(item, schema["items"], root_schema, "%s[%d]" % (path, index))


if __name__ == "__main__":
    unittest.main()
