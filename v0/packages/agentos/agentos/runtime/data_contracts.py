"""Inter-agent data contracts — validation and compression for agent outputs."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    """Result of validating agent output against a data contract."""

    valid: bool
    errors: list[str] = []


def validate_output(output: str, schema: dict[str, Any]) -> ValidationResult:
    """Validate agent output against a JSON Schema data contract.

    Performs structural validation:
    - Checks output is valid JSON
    - Validates required fields from schema
    - Validates type constraints

    Uses a lightweight built-in validator (no jsonschema dependency).
    """
    # Try to parse as JSON
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        # Not JSON — treat as plain text, validate against string schema
        if schema.get("type") == "string":
            return ValidationResult(valid=True)
        return ValidationResult(
            valid=False,
            errors=["Output is not valid JSON"],
        )

    return _validate_value(data, schema)


def _validate_value(value: Any, schema: dict[str, Any]) -> ValidationResult:
    """Validate a value against a JSON Schema (subset)."""
    errors: list[str] = []
    schema_type = schema.get("type")

    if schema_type == "object":
        if not isinstance(value, dict):
            return ValidationResult(valid=False, errors=["Expected object, got " + type(value).__name__])

        # Check required fields
        for field in schema.get("required", []):
            if field not in value:
                errors.append(f"Missing required field: '{field}'")

        # Check property types
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in value:
                sub_result = _validate_value(value[prop_name], prop_schema)
                errors.extend(sub_result.errors)

    elif schema_type == "array":
        if not isinstance(value, list):
            return ValidationResult(valid=False, errors=["Expected array, got " + type(value).__name__])
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(value):
                sub_result = _validate_value(item, items_schema)
                for err in sub_result.errors:
                    errors.append(f"[{i}]: {err}")

    elif schema_type == "string":
        if not isinstance(value, str):
            errors.append(f"Expected string, got {type(value).__name__}")

    elif schema_type == "number":
        if not isinstance(value, (int, float)):
            errors.append(f"Expected number, got {type(value).__name__}")

    elif schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"Expected integer, got {type(value).__name__}")

    elif schema_type == "boolean":
        if not isinstance(value, bool):
            errors.append(f"Expected boolean, got {type(value).__name__}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def compress_for_context(
    text: str,
    max_chars: int,
) -> str:
    """Compress text to fit within a character budget.

    Strategy:
    1. If text fits, return as-is
    2. If text is JSON, extract top-level keys with truncated values
    3. Otherwise, truncate with ellipsis
    """
    if len(text) <= max_chars:
        return text

    # Try JSON compression
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _compress_json_object(data, max_chars)
        elif isinstance(data, list):
            return _compress_json_array(data, max_chars)
    except (json.JSONDecodeError, TypeError):
        pass

    # Plain text truncation
    return text[: max_chars - 30] + "\n\n[... truncated to fit context]"


def _compress_json_object(data: dict[str, Any], max_chars: int) -> str:
    """Compress a JSON object by truncating values."""
    # Start with keys and short values
    result: dict[str, Any] = {}
    budget = max_chars - 50  # Reserve space for overhead

    for key, value in data.items():
        value_str = json.dumps(value)
        if len(value_str) > 200:
            if isinstance(value, str):
                result[key] = value[:150] + "..."
            elif isinstance(value, list):
                result[key] = f"[{len(value)} items]"
            elif isinstance(value, dict):
                result[key] = f"{{... {len(value)} keys}}"
            else:
                result[key] = value
        else:
            result[key] = value

        current = json.dumps(result, indent=2)
        if len(current) > budget:
            result[key] = "[truncated]"
            break

    return json.dumps(result, indent=2)


def _compress_json_array(data: list[Any], max_chars: int) -> str:
    """Compress a JSON array by keeping first/last items."""
    if not data:
        return "[]"

    full = json.dumps(data, indent=2)
    if len(full) <= max_chars:
        return full

    # Keep first 3 and last item
    keep = min(3, len(data))
    subset = data[:keep]
    result = json.dumps(subset, indent=2)

    remaining = len(data) - keep
    if remaining > 0:
        result = result.rstrip("]").rstrip()
        result += f',\n  "... {remaining} more items"\n]'

    return result
