"""Minimal JSON Schema subset for action arguments and model answers.

Supports: type (object, string, integer, boolean, array), properties, required,
additionalProperties false, enum, minimum, maximum, maxLength, items. That is all the
action catalogs use; anything else in a schema is a programming error.
"""
from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict,
    "string": str,
    "integer": int,
    "boolean": bool,
    "array": list,
}


def validate(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        if not isinstance(value, _TYPES[expected]) or (expected == "integer" and isinstance(value, bool)):
            return [f"{path}: expected {expected}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")
    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, item in value.items():
            if key in props:
                errors += validate(props[key], item, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unexpected field")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors += validate(schema["items"], item, f"{path}[{index}]")
    return errors
