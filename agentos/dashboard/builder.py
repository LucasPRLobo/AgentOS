"""Visual Workflow Builder backend — CRUD, validation, and template storage."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

import yaml

from agentos.schemas.workflow import WorkflowDefinition
from agentos.validation.workflow_verifier import WorkflowVerifier


class WorkflowTemplate:
    """A stored workflow template."""

    def __init__(
        self,
        template_id: str,
        name: str,
        description: str,
        workflow_yaml: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.template_id = template_id
        self.name = name
        self.description = description
        self.workflow_yaml = workflow_yaml
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "workflow_yaml": self.workflow_yaml,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ValidationResult:
    """Result of workflow validation."""

    def __init__(self, valid: bool, errors: list[str] | None = None) -> None:
        self.valid = valid
        self.errors = errors or []

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": self.errors}


class WorkflowBuilder:
    """Backend for visual workflow builder.

    Provides CRUD for workflow templates, YAML <-> JSON round-trip,
    and live validation via WorkflowVerifier.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_templates (
                template_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                workflow_yaml TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def create_template(
        self, name: str, workflow_yaml: str, description: str = ""
    ) -> WorkflowTemplate:
        """Create a new workflow template."""
        template_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            self._conn.execute(
                "INSERT INTO workflow_templates (template_id, name, description, workflow_yaml, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (template_id, name, description, workflow_yaml, now, now),
            )
            self._conn.commit()
        return WorkflowTemplate(template_id, name, description, workflow_yaml, now, now)

    def get_template(self, template_id: str) -> WorkflowTemplate | None:
        """Get a template by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT template_id, name, description, workflow_yaml, created_at, updated_at FROM workflow_templates WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return WorkflowTemplate(*row)

    def list_templates(self) -> list[WorkflowTemplate]:
        """List all templates."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT template_id, name, description, workflow_yaml, created_at, updated_at FROM workflow_templates ORDER BY updated_at DESC"
            ).fetchall()
        return [WorkflowTemplate(*r) for r in rows]

    def update_template(
        self,
        template_id: str,
        name: str | None = None,
        workflow_yaml: str | None = None,
        description: str | None = None,
    ) -> WorkflowTemplate | None:
        """Update an existing template. Returns None if not found."""
        existing = self.get_template(template_id)
        if existing is None:
            return None

        new_name = name if name is not None else existing.name
        new_yaml = workflow_yaml if workflow_yaml is not None else existing.workflow_yaml
        new_desc = description if description is not None else existing.description
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        with self._lock:
            self._conn.execute(
                "UPDATE workflow_templates SET name=?, description=?, workflow_yaml=?, updated_at=? WHERE template_id=?",
                (new_name, new_desc, new_yaml, now, template_id),
            )
            self._conn.commit()
        return WorkflowTemplate(template_id, new_name, new_desc, new_yaml, existing.created_at, now)

    def delete_template(self, template_id: str) -> bool:
        """Delete a template. Returns True if found and deleted."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM workflow_templates WHERE template_id = ?", (template_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def validate_workflow(self, workflow_yaml: str) -> ValidationResult:
        """Validate a workflow YAML string.

        Parses the YAML, validates the Pydantic schema, and runs
        WorkflowVerifier checks (DAG validity, agent references, etc.).
        """
        errors: list[str] = []

        # Parse YAML
        try:
            data = yaml.safe_load(workflow_yaml)
        except yaml.YAMLError as e:
            return ValidationResult(False, [f"YAML parse error: {e}"])

        if not isinstance(data, dict):
            return ValidationResult(False, ["YAML must be a mapping"])

        # Validate Pydantic schema
        try:
            workflow = WorkflowDefinition.model_validate(data)
        except Exception as e:
            return ValidationResult(False, [f"Schema validation error: {e}"])

        # Run WorkflowVerifier
        try:
            verifier = WorkflowVerifier()
            result = verifier.verify(workflow)
            if not result.valid:
                errors.extend(result.errors)
        except Exception as e:
            errors.append(f"Verification error: {e}")

        return ValidationResult(len(errors) == 0, errors)

    @staticmethod
    def yaml_to_json(workflow_yaml: str) -> str:
        """Convert YAML workflow to JSON."""
        data = yaml.safe_load(workflow_yaml)
        return json.dumps(data, indent=2)

    @staticmethod
    def json_to_yaml(workflow_json: str) -> str:
        """Convert JSON workflow to YAML."""
        data = json.loads(workflow_json)
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
