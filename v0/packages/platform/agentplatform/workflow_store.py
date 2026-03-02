"""Workflow store — filesystem-based workflow persistence."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.identifiers import generate_run_id
from agentos.schemas.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)

_DEFAULT_DIR = os.path.expanduser("~/.agentos/workflows")


class WorkflowSummary(BaseModel):
    """Lightweight summary for workflow listings."""

    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    node_count: int = 0
    edge_count: int = 0
    domain_pack: str = ""
    created_at: str = ""
    updated_at: str = ""
    template_source: str | None = None


class WorkflowStore:
    """Save/load workflows as JSON files on the local filesystem.

    Each workflow is stored as ``{workflow_id}.json`` in the base directory.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or _DEFAULT_DIR)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def save(self, workflow: WorkflowDefinition) -> None:
        """Save a workflow definition to disk."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(workflow.id)
        # Update the updated_at timestamp
        data = json.loads(workflow.model_dump_json())
        data["updated_at"] = datetime.now(UTC).isoformat()
        path.write_text(json.dumps(data, indent=2) + "\n")

    def load(self, workflow_id: str) -> WorkflowDefinition:
        """Load a workflow definition by ID.

        Raises:
            FileNotFoundError: If the workflow doesn't exist.
        """
        path = self._path_for(workflow_id)
        if not path.exists():
            raise FileNotFoundError(f"Workflow '{workflow_id}' not found")
        data = json.loads(path.read_text())
        return WorkflowDefinition.model_validate(data)

    def list(self) -> list[WorkflowSummary]:
        """List all saved workflows (sorted by updated_at descending)."""
        if not self._base_dir.exists():
            return []

        summaries: list[WorkflowSummary] = []
        for path in self._base_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                summaries.append(WorkflowSummary(
                    id=data.get("id", path.stem),
                    name=data.get("name", "Untitled"),
                    description=data.get("description", ""),
                    version=data.get("version", "1.0.0"),
                    node_count=len(data.get("nodes", [])),
                    edge_count=len(data.get("edges", [])),
                    domain_pack=data.get("domain_pack", ""),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                    template_source=data.get("template_source"),
                ))
            except Exception as exc:
                logger.warning("Failed to read workflow %s: %s", path, exc)

        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    def delete(self, workflow_id: str) -> None:
        """Delete a workflow by ID.

        Raises:
            FileNotFoundError: If the workflow doesn't exist.
        """
        path = self._path_for(workflow_id)
        if not path.exists():
            raise FileNotFoundError(f"Workflow '{workflow_id}' not found")
        path.unlink()

    def clone(self, workflow_id: str) -> WorkflowDefinition:
        """Clone a workflow with a new ID and timestamps.

        Raises:
            FileNotFoundError: If the source workflow doesn't exist.
        """
        original = self.load(workflow_id)
        now = datetime.now(UTC).isoformat()
        cloned = original.model_copy(update={
            "id": str(generate_run_id()),
            "name": f"{original.name} (copy)",
            "created_at": now,
            "updated_at": now,
            "template_source": original.template_source or original.id,
        })
        self.save(cloned)
        return cloned

    def exists(self, workflow_id: str) -> bool:
        """Check if a workflow exists."""
        return self._path_for(workflow_id).exists()

    def _path_for(self, workflow_id: str) -> Path:
        """Return the file path for a workflow ID."""
        # Sanitize to prevent path traversal
        safe_id = Path(workflow_id).name
        return self._base_dir / f"{safe_id}.json"
