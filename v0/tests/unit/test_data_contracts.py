"""Tests for inter-agent data contracts and compression."""

import json

import pytest

from agentos.runtime.data_contracts import (
    ValidationResult,
    compress_for_context,
    validate_output,
)


class TestValidateOutput:
    def test_valid_object(self) -> None:
        schema = {
            "type": "object",
            "required": ["title", "summary"],
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
            },
        }
        output = json.dumps({"title": "Test", "summary": "A test."})
        result = validate_output(output, schema)
        assert result.valid is True
        assert result.errors == []

    def test_missing_required_field(self) -> None:
        schema = {
            "type": "object",
            "required": ["title", "summary"],
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
            },
        }
        output = json.dumps({"title": "Test"})
        result = validate_output(output, schema)
        assert result.valid is False
        assert any("summary" in e for e in result.errors)

    def test_wrong_type(self) -> None:
        schema = {"type": "object"}
        output = json.dumps([1, 2, 3])
        result = validate_output(output, schema)
        assert result.valid is False
        assert any("Expected object" in e for e in result.errors)

    def test_string_schema_with_plain_text(self) -> None:
        schema = {"type": "string"}
        result = validate_output("Just some plain text", schema)
        assert result.valid is True

    def test_invalid_json_non_string_schema(self) -> None:
        schema = {"type": "object"}
        result = validate_output("not json {{{", schema)
        assert result.valid is False
        assert any("not valid JSON" in e for e in result.errors)

    def test_array_validation(self) -> None:
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        output = json.dumps(["a", "b", "c"])
        result = validate_output(output, schema)
        assert result.valid is True

    def test_array_wrong_item_type(self) -> None:
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        output = json.dumps(["a", 42, "c"])
        result = validate_output(output, schema)
        assert result.valid is False

    def test_nested_object(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "meta": {
                    "type": "object",
                    "required": ["author"],
                    "properties": {"author": {"type": "string"}},
                },
            },
        }
        output = json.dumps({"meta": {"author": "Alice"}})
        result = validate_output(output, schema)
        assert result.valid is True


class TestCompressForContext:
    def test_short_text_unchanged(self) -> None:
        text = "Hello world"
        assert compress_for_context(text, 1000) == text

    def test_long_text_truncated(self) -> None:
        text = "x" * 10_000
        result = compress_for_context(text, 500)
        assert len(result) <= 510  # Allow small overhead from suffix
        assert "truncated" in result

    def test_json_object_compressed(self) -> None:
        data = {"key1": "short", "key2": "x" * 1000, "key3": "also short"}
        text = json.dumps(data)
        result = compress_for_context(text, 200)
        assert len(result) <= 250  # Allow some overhead
        assert "key1" in result

    def test_json_array_compressed(self) -> None:
        data = list(range(100))
        text = json.dumps(data)
        result = compress_for_context(text, 100)
        assert "more items" in result

    def test_exact_limit(self) -> None:
        text = "Hello"
        assert compress_for_context(text, 5) == text
