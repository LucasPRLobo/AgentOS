"""Deterministic hashing — canonical JSON serialization and stable sha256."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def canonical_json(data: Any) -> str:
    """Produce a canonical JSON string with sorted keys and no extra whitespace.

    Accepts dicts, lists, Pydantic models, or any JSON-serializable value.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hash(data: str | bytes) -> str:
    """Compute SHA-256 hex digest of a string or bytes."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_model(model: BaseModel) -> str:
    """Compute a stable SHA-256 hash of a Pydantic model via canonical JSON."""
    return sha256_hash(canonical_json(model))


def hash_dict(data: dict[str, Any]) -> str:
    """Compute a stable SHA-256 hash of a dict via canonical JSON."""
    return sha256_hash(canonical_json(data))


def hash_file(path: str | Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
