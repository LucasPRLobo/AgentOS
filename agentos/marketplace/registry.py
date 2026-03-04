"""Marketplace registry — template CRUD, metrics, import/export."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

import yaml

from agentos.schemas.marketplace import MarketplaceTemplate, TemplateMetrics


class MarketplaceRegistry:
    """Registry for marketplace workflow templates.

    Provides CRUD operations, verified metrics attachment,
    and import/export of workflow templates with metadata.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS marketplace_templates (
                template_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'general',
                tags TEXT NOT NULL DEFAULT '[]',
                workflow_yaml TEXT NOT NULL,
                metrics TEXT NOT NULL DEFAULT '{}',
                verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                downloads INTEGER NOT NULL DEFAULT 0
            );
        """)
        self._conn.commit()

    def publish(
        self,
        name: str,
        workflow_yaml: str,
        description: str = "",
        author: str = "",
        category: str = "general",
        tags: list[str] | None = None,
    ) -> MarketplaceTemplate:
        """Publish a new template to the marketplace."""
        template_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        tag_list = tags or []
        metrics = TemplateMetrics()

        with self._lock:
            self._conn.execute(
                """INSERT INTO marketplace_templates
                   (template_id, name, description, author, category, tags,
                    workflow_yaml, metrics, verified, created_at, updated_at, downloads)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0)""",
                (template_id, name, description, author, category,
                 json.dumps(tag_list), workflow_yaml,
                 metrics.model_dump_json(), now, now),
            )
            self._conn.commit()

        return MarketplaceTemplate(
            template_id=template_id,
            name=name,
            description=description,
            author=author,
            category=category,
            tags=tag_list,
            workflow_yaml=workflow_yaml,
            metrics=metrics,
        )

    def get(self, template_id: str) -> MarketplaceTemplate | None:
        """Get a template by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM marketplace_templates WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_template(row)

    def list_templates(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        verified_only: bool = False,
    ) -> list[MarketplaceTemplate]:
        """List templates with optional filters."""
        clauses: list[str] = []
        params: list[object] = []

        if category:
            clauses.append("category = ?")
            params.append(category)
        if verified_only:
            clauses.append("verified = 1")

        sql = "SELECT * FROM marketplace_templates"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY downloads DESC, updated_at DESC"

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        templates = [self._row_to_template(r) for r in rows]

        if tags:
            tag_set = set(tags)
            templates = [t for t in templates if tag_set & set(t.tags)]

        return templates

    def update_metrics(self, template_id: str, metrics: TemplateMetrics) -> bool:
        """Update metrics for a template."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE marketplace_templates SET metrics = ?, updated_at = ? WHERE template_id = ?",
                (metrics.model_dump_json(), now, template_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def verify(self, template_id: str) -> bool:
        """Mark a template as verified."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE marketplace_templates SET verified = 1 WHERE template_id = ?",
                (template_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def increment_downloads(self, template_id: str) -> bool:
        """Increment download count."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE marketplace_templates SET downloads = downloads + 1 WHERE template_id = ?",
                (template_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete(self, template_id: str) -> bool:
        """Delete a template."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM marketplace_templates WHERE template_id = ?",
                (template_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def export_template(self, template_id: str) -> str | None:
        """Export a template as JSON with full metadata."""
        template = self.get(template_id)
        if template is None:
            return None
        return template.model_dump_json(indent=2)

    def import_template(self, json_data: str) -> MarketplaceTemplate:
        """Import a template from JSON."""
        template = MarketplaceTemplate.model_validate_json(json_data)
        # Assign new ID to avoid collisions
        template.template_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        with self._lock:
            self._conn.execute(
                """INSERT INTO marketplace_templates
                   (template_id, name, description, author, category, tags,
                    workflow_yaml, metrics, verified, created_at, updated_at, downloads)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (template.template_id, template.name, template.description,
                 template.author, template.category,
                 json.dumps(template.tags), template.workflow_yaml,
                 template.metrics.model_dump_json(),
                 1 if template.verified else 0, now, now, 0),
            )
            self._conn.commit()

        return template

    @staticmethod
    def _row_to_template(row: tuple) -> MarketplaceTemplate:
        return MarketplaceTemplate(
            template_id=row[0],
            name=row[1],
            description=row[2],
            author=row[3],
            category=row[4],
            tags=json.loads(row[5]),
            workflow_yaml=row[6],
            metrics=TemplateMetrics.model_validate_json(row[7]),
            verified=bool(row[8]),
            created_at=row[9],
            updated_at=row[10],
            downloads=row[11],
        )
