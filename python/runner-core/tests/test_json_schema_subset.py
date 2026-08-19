import unittest

from infergrade.capability_contract import capability_run_schema_path
from infergrade.json_schema_subset import validate_json_schema


class JsonSchemaSubsetTests(unittest.TestCase):
    def test_external_runtime_selector_reference_is_enforced(self):
        schema = {
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"$ref": "runtime_selector.schema.json"}
            },
            "additionalProperties": False,
        }
        selector = {
            "runtime_selector_version": "0.3",
            "runtime_family": "llama.cpp",
            "platform": {"system": "macos", "arch": "arm64"},
            "accelerator": {"vendor": "apple", "api": "metal"},
            "delivery": {
                "mode": "bundled",
                "binary_set": "llama.cpp",
                "source": "desktop_bundle",
                "selected_by": "run_config",
            },
            "compatibility": {
                "status": "ready",
                "reason_codes": [],
                "probes": [],
            },
            "support": {
                "tier": "technical_beta",
                "claim_boundary": "Scoped runtime evidence only.",
            },
            "fallback": {"allowed": False},
        }

        self.assertEqual(
            validate_json_schema(
                {"selector": selector},
                schema,
                capability_run_schema_path(),
            ),
            [],
        )
        selector["platform"]["unexpected"] = True
        self.assertTrue(
            validate_json_schema(
                {"selector": selector},
                schema,
                capability_run_schema_path(),
            )
        )

    def test_additional_properties_bool_integer_and_conditionals_fail_closed(self):
        schema = {
            "type": "object",
            "required": ["count", "state"],
            "properties": {
                "count": {"type": "integer"},
                "state": {"enum": ["scored", "failed"]},
                "score": {"type": "number"},
            },
            "additionalProperties": False,
            "allOf": [
                {
                    "if": {
                        "properties": {"state": {"const": "scored"}},
                        "required": ["state"],
                    },
                    "then": {"required": ["score"]},
                }
            ],
        }
        schema_path = capability_run_schema_path()

        self.assertEqual(
            validate_json_schema(
                {"count": 1, "state": "scored", "score": 0.5},
                schema,
                schema_path,
            ),
            [],
        )
        self.assertTrue(
            validate_json_schema(
                {"count": True, "state": "scored", "score": 0.5},
                schema,
                schema_path,
            )
        )
        self.assertTrue(
            validate_json_schema(
                {"count": 1, "state": "scored"},
                schema,
                schema_path,
            )
        )
        extra_errors = validate_json_schema(
            {"count": 1, "state": "failed", "private_secret_key": 1},
            schema,
            schema_path,
        )
        self.assertTrue(extra_errors)
        self.assertNotIn("private_secret_key", " ".join(extra_errors))

    def test_malformed_container_values_return_errors_without_throwing(self):
        schema = {
            "type": "object",
            "required": ["algorithm", "items"],
            "properties": {
                "algorithm": {"enum": ["supported"]},
                "items": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
        }
        schema_path = capability_run_schema_path()

        for value in (
            {"algorithm": [], "items": []},
            {"algorithm": {}, "items": []},
            {"algorithm": "supported", "items": {}},
            [],
        ):
            with self.subTest(value=value):
                self.assertTrue(validate_json_schema(value, schema, schema_path))


if __name__ == "__main__":
    unittest.main()
