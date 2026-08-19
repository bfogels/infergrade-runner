"""Small stdlib JSON Schema subset used for Runner-owned contracts."""

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List


class SchemaValidationError(ValueError):
    pass


def validate_json_schema(
    value: Any,
    schema: Dict[str, Any],
    schema_path: Path,
) -> List[str]:
    """Return the first structural error for the schema keywords Runner uses."""
    try:
        _validate(value, schema, schema, Path(schema_path), "$")
    except SchemaValidationError as exc:
        return [str(exc)]
    return []


def _validate(
    value: Any,
    schema: Dict[str, Any],
    root_schema: Dict[str, Any],
    schema_path: Path,
    value_path: str,
) -> None:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        target, target_root, target_path = _resolve_reference(
            reference,
            root_schema,
            schema_path,
        )
        _validate(value, target, target_root, target_path, value_path)

    for item_schema in list(schema.get("allOf") or []):
        _validate(value, item_schema, root_schema, schema_path, value_path)

    if "anyOf" in schema and not any(
        _matches(value, item, root_schema, schema_path, value_path)
        for item in schema["anyOf"]
    ):
        raise SchemaValidationError("%s must match at least one anyOf branch" % value_path)

    if "oneOf" in schema:
        matches = sum(
            1
            for item in schema["oneOf"]
            if _matches(value, item, root_schema, schema_path, value_path)
        )
        if matches != 1:
            raise SchemaValidationError(
                "%s must match exactly one oneOf branch" % value_path
            )

    if "not" in schema and _matches(
        value,
        schema["not"],
        root_schema,
        schema_path,
        value_path,
    ):
        raise SchemaValidationError("%s must not match the prohibited schema" % value_path)

    if "if" in schema:
        branch = schema.get("then") if _matches(
            value,
            schema["if"],
            root_schema,
            schema_path,
            value_path,
        ) else schema.get("else")
        if isinstance(branch, dict):
            _validate(value, branch, root_schema, schema_path, value_path)

    if "const" in schema and not _json_equal(value, schema["const"]):
        raise SchemaValidationError("%s must equal the schema constant" % value_path)
    if "enum" in schema and not any(
        _json_equal(value, allowed) for allowed in schema["enum"]
    ):
        raise SchemaValidationError("%s must be one of the schema enum values" % value_path)

    schema_type = schema.get("type")
    if schema_type is not None and not _matches_type(value, schema_type):
        raise SchemaValidationError("%s has an invalid JSON type" % value_path)

    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise SchemaValidationError("%s is shorter than minLength" % value_path)
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise SchemaValidationError("%s is longer than maxLength" % value_path)
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            raise SchemaValidationError("%s does not match the required pattern" % value_path)

    if _is_number(value):
        if not math.isfinite(float(value)):
            raise SchemaValidationError("%s must be a finite JSON number" % value_path)
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError("%s is below minimum" % value_path)
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError("%s is above maximum" % value_path)
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise SchemaValidationError("%s is not above exclusiveMinimum" % value_path)
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise SchemaValidationError("%s is not below exclusiveMaximum" % value_path)

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for required in list(schema.get("required") or []):
            if required not in value:
                raise SchemaValidationError(
                    "%s.%s is required by the JSON schema" % (value_path, required)
                )
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            item_path = "%s.%s" % (value_path, key)
            if key in properties:
                _validate(item, properties[key], root_schema, schema_path, item_path)
            elif additional is False:
                raise SchemaValidationError(
                    "%s contains a property not allowed by the JSON schema"
                    % value_path
                )
            elif isinstance(additional, dict):
                _validate(item, additional, root_schema, schema_path, item_path)

    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise SchemaValidationError("%s has fewer than minItems" % value_path)
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise SchemaValidationError("%s has more than maxItems" % value_path)
        if schema.get("uniqueItems") is True:
            encoded = [
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(encoded) != len(set(encoded)):
                raise SchemaValidationError("%s must contain unique items" % value_path)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(
                    item,
                    item_schema,
                    root_schema,
                    schema_path,
                    "%s[%d]" % (value_path, index),
                )


def _matches(
    value: Any,
    schema: Dict[str, Any],
    root_schema: Dict[str, Any],
    schema_path: Path,
    value_path: str,
) -> bool:
    try:
        _validate(value, schema, root_schema, schema_path, value_path)
    except SchemaValidationError:
        return False
    return True


def _resolve_reference(
    reference: str,
    root_schema: Dict[str, Any],
    schema_path: Path,
) -> tuple:
    if reference.startswith("#"):
        return _resolve_pointer(root_schema, reference[1:]), root_schema, schema_path
    filename, separator, fragment = reference.partition("#")
    target_path = (schema_path.parent / filename).resolve()
    target_root = _load_schema(str(target_path))
    target = _resolve_pointer(target_root, fragment) if separator else target_root
    return target, target_root, target_path


def _resolve_pointer(document: Dict[str, Any], pointer: str) -> Dict[str, Any]:
    target: Any = document
    for raw_part in pointer.lstrip("/").split("/") if pointer else []:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            raise SchemaValidationError("JSON schema reference cannot be resolved")
        target = target[part]
    if not isinstance(target, dict):
        raise SchemaValidationError("JSON schema reference is not an object")
    return target


@lru_cache(maxsize=16)
def _load_schema(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _matches_type(value: Any, schema_type: Any) -> bool:
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    return any(
        (item == "null" and value is None)
        or (item == "object" and isinstance(value, dict))
        or (item == "array" and isinstance(value, list))
        or (item == "string" and isinstance(value, str))
        or (
            item == "integer"
            and isinstance(value, int)
            and not isinstance(value, bool)
        )
        or (item == "number" and _is_number(value))
        or (item == "boolean" and isinstance(value, bool))
        for item in types
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right
