"""Tests for deterministic hashing — canonical JSON and stable sha256."""

import tempfile
from pathlib import Path

from pydantic import BaseModel

from agentos.integrity.hashing import (
    canonical_json,
    hash_dict,
    hash_file,
    hash_model,
    sha256_hash,
)


class SampleModel(BaseModel):
    name: str
    value: int
    nested: dict[str, int] = {}


class TestCanonicalJson:
    def test_sorted_keys(self) -> None:
        result = canonical_json({"z": 1, "a": 2, "m": 3})
        assert result == '{"a":2,"m":3,"z":1}'

    def test_no_whitespace(self) -> None:
        result = canonical_json({"key": "value"})
        assert " " not in result

    def test_nested_sorted(self) -> None:
        result = canonical_json({"b": {"z": 1, "a": 2}, "a": 1})
        assert result == '{"a":1,"b":{"a":2,"z":1}}'

    def test_pydantic_model(self) -> None:
        model = SampleModel(name="test", value=42, nested={"b": 2, "a": 1})
        result = canonical_json(model)
        assert '"a":1' in result
        assert result.index('"a"') < result.index('"b"')

    def test_deterministic(self) -> None:
        data = {"x": [1, 2, 3], "a": "hello"}
        assert canonical_json(data) == canonical_json(data)

    def test_list_order_preserved(self) -> None:
        result = canonical_json([3, 1, 2])
        assert result == "[3,1,2]"


class TestSha256Hash:
    def test_string_hash(self) -> None:
        h = sha256_hash("hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_bytes_hash(self) -> None:
        h = sha256_hash(b"hello")
        assert h == sha256_hash("hello")

    def test_different_inputs(self) -> None:
        assert sha256_hash("a") != sha256_hash("b")

    def test_deterministic(self) -> None:
        assert sha256_hash("test") == sha256_hash("test")


class TestHashModel:
    def test_same_model_same_hash(self) -> None:
        m1 = SampleModel(name="x", value=1)
        m2 = SampleModel(name="x", value=1)
        assert hash_model(m1) == hash_model(m2)

    def test_different_model_different_hash(self) -> None:
        m1 = SampleModel(name="x", value=1)
        m2 = SampleModel(name="x", value=2)
        assert hash_model(m1) != hash_model(m2)

    def test_field_order_irrelevant(self) -> None:
        # Pydantic models have fixed field order, but canonical JSON sorts keys
        m1 = SampleModel(name="a", value=1, nested={"z": 9, "a": 1})
        m2 = SampleModel(name="a", value=1, nested={"a": 1, "z": 9})
        assert hash_model(m1) == hash_model(m2)


class TestHashDict:
    def test_same_dict_same_hash(self) -> None:
        assert hash_dict({"a": 1}) == hash_dict({"a": 1})

    def test_key_order_irrelevant(self) -> None:
        assert hash_dict({"z": 1, "a": 2}) == hash_dict({"a": 2, "z": 1})


class TestHashFile:
    def test_hash_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name

        h = hash_file(path)
        assert len(h) == 64

        # Same content = same hash
        h2 = hash_file(path)
        assert h == h2
        Path(path).unlink()

    def test_different_files_different_hash(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f1:
            f1.write("content A")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f2:
            f2.write("content B")
            p2 = f2.name

        assert hash_file(p1) != hash_file(p2)
        Path(p1).unlink()
        Path(p2).unlink()
