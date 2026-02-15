"""Template store — read-only catalogue of built-in workflow templates."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel

from agentos.schemas.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateSummary(BaseModel):
    """Lightweight summary for template listings."""

    id: str
    name: str
    description: str = ""
    category: str = ""
    agent_count: int = 0
    estimated_cost: str = ""
    domain_pack: str = ""
    tags: list[str] = []


class TemplateStore:
    """Read-only store for built-in workflow templates.

    Templates are JSON files bundled with the package under
    ``agentplatform/templates/*.json``.  They are loaded on demand and
    cached in memory.
    """

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        self._dir = Path(templates_dir) if templates_dir else _TEMPLATES_DIR
        self._cache: dict[str, WorkflowDefinition] = {}
        self._meta_cache: dict[str, dict] = {}

    def list(self, *, domain_pack: str | None = None) -> list[TemplateSummary]:
        """List available templates, optionally filtered by domain pack."""
        self._ensure_loaded()
        summaries: list[TemplateSummary] = []
        for tid, meta in self._meta_cache.items():
            if domain_pack and meta.get("domain_pack", "") != domain_pack:
                continue
            wf = self._cache[tid]
            summaries.append(TemplateSummary(
                id=tid,
                name=wf.name,
                description=wf.description,
                category=meta.get("category", ""),
                agent_count=len(wf.nodes),
                estimated_cost=meta.get("estimated_cost", ""),
                domain_pack=wf.domain_pack,
                tags=meta.get("tags", []),
            ))
        summaries.sort(key=lambda s: s.name)
        return summaries

    def get(self, template_id: str) -> WorkflowDefinition:
        """Load a template by ID.

        Raises:
            KeyError: If the template doesn't exist.
        """
        self._ensure_loaded()
        if template_id not in self._cache:
            raise KeyError(f"Template '{template_id}' not found")
        return self._cache[template_id]

    def get_meta(self, template_id: str) -> dict:
        """Return template metadata (category, tags, estimated_cost)."""
        self._ensure_loaded()
        if template_id not in self._meta_cache:
            raise KeyError(f"Template '{template_id}' not found")
        return self._meta_cache[template_id]

    def exists(self, template_id: str) -> bool:
        self._ensure_loaded()
        return template_id in self._cache

    def _ensure_loaded(self) -> None:
        """Lazy-load all template files from disk on first access."""
        if self._cache:
            return
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
                # Extract metadata fields that sit outside WorkflowDefinition
                meta = {
                    "category": raw.pop("_category", ""),
                    "tags": raw.pop("_tags", []),
                    "estimated_cost": raw.pop("_estimated_cost", ""),
                }
                wf = WorkflowDefinition.model_validate(raw)
                self._cache[wf.id] = wf
                self._meta_cache[wf.id] = {**meta, "domain_pack": wf.domain_pack}
            except Exception as exc:
                logger.warning("Failed to load template %s: %s", path, exc)
