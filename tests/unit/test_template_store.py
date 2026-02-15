"""Unit tests for TemplateStore — built-in workflow template catalogue."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agentplatform.template_store import TemplateStore, TemplateSummary


def _make_template(tid: str, name: str, **extra: object) -> dict:
    """Create a minimal valid template JSON dict."""
    return {
        "_category": extra.pop("_category", "test"),
        "_tags": extra.pop("_tags", ["t1"]),
        "_estimated_cost": extra.pop("_estimated_cost", "~$0.10"),
        "id": tid,
        "name": name,
        "description": f"Template {name}",
        "version": "1.0.0",
        "domain_pack": "codeos",
        "nodes": [
            {
                "id": "n1",
                "role": "custom",
                "display_name": "Agent A",
                "position": {"x": 100, "y": 100},
                "config": {
                    "model": "gpt-4o-mini",
                    "system_prompt": "Do something.",
                    "persona_preset": "analytical",
                    "tools": ["file_read"],
                    "budget": None,
                    "max_steps": 10,
                    "advanced": None,
                },
            }
        ],
        "edges": [],
        "variables": [],
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "template_source": None,
        **extra,
    }


@pytest.fixture()
def store_dir(tmp_path: Path) -> Path:
    """Create a temp directory with a couple of template JSON files."""
    t1 = _make_template("tpl_alpha", "Alpha", _category="research", _tags=["r1"])
    t2 = _make_template("tpl_beta", "Beta", _category="productivity", _tags=["p1"], domain_pack="labos")
    (tmp_path / "alpha.json").write_text(json.dumps(t1))
    (tmp_path / "beta.json").write_text(json.dumps(t2))
    return tmp_path


class TestTemplateStore:
    def test_list_all(self, store_dir: Path) -> None:
        store = TemplateStore(store_dir)
        summaries = store.list()
        assert len(summaries) == 2
        names = {s.name for s in summaries}
        assert names == {"Alpha", "Beta"}

    def test_list_filter_by_domain_pack(self, store_dir: Path) -> None:
        store = TemplateStore(store_dir)
        result = store.list(domain_pack="labos")
        assert len(result) == 1
        assert result[0].name == "Beta"

    def test_get_existing(self, store_dir: Path) -> None:
        store = TemplateStore(store_dir)
        wf = store.get("tpl_alpha")
        assert wf.id == "tpl_alpha"
        assert wf.name == "Alpha"
        assert len(wf.nodes) == 1

    def test_get_not_found(self, store_dir: Path) -> None:
        store = TemplateStore(store_dir)
        with pytest.raises(KeyError, match="not found"):
            store.get("tpl_nonexistent")

    def test_exists(self, store_dir: Path) -> None:
        store = TemplateStore(store_dir)
        assert store.exists("tpl_alpha") is True
        assert store.exists("tpl_nonexistent") is False

    def test_get_meta(self, store_dir: Path) -> None:
        store = TemplateStore(store_dir)
        meta = store.get_meta("tpl_alpha")
        assert meta["category"] == "research"
        assert meta["tags"] == ["r1"]

    def test_summary_fields(self, store_dir: Path) -> None:
        store = TemplateStore(store_dir)
        summaries = store.list()
        alpha = next(s for s in summaries if s.id == "tpl_alpha")
        assert alpha.category == "research"
        assert alpha.agent_count == 1
        assert alpha.estimated_cost == "~$0.10"

    def test_empty_dir(self, tmp_path: Path) -> None:
        store = TemplateStore(tmp_path)
        assert store.list() == []

    def test_nonexistent_dir(self) -> None:
        store = TemplateStore("/tmp/nonexistent_templates_dir_abc123")
        assert store.list() == []


class TestBuiltinTemplates:
    """Verify the actual bundled template files load correctly."""

    def test_bundled_templates_load(self) -> None:
        store = TemplateStore()  # Uses default built-in directory
        summaries = store.list()
        # We created 8 templates
        assert len(summaries) == 8

    def test_bundled_template_ids(self) -> None:
        store = TemplateStore()
        ids = {s.id for s in store.list()}
        expected = {
            "tpl_research_report",
            "tpl_file_organizer",
            "tpl_content_pipeline",
            "tpl_code_review",
            "tpl_email_summary",
            "tpl_data_analysis",
            "tpl_meeting_notes",
            "tpl_competitor_analysis",
        }
        assert ids == expected

    def test_bundled_template_get(self) -> None:
        store = TemplateStore()
        wf = store.get("tpl_research_report")
        assert wf.name == "Research Report"
        assert len(wf.nodes) == 4
        assert len(wf.edges) == 3
