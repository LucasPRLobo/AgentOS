"""Tests for agent marketplace registry."""

from __future__ import annotations

import json

import pytest

from agentos.marketplace.registry import MarketplaceRegistry
from agentos.schemas.marketplace import MarketplaceTemplate, TemplateMetrics


SAMPLE_YAML = "name: test\nversion: '1.0'\nagents: {}\ntasks: {}\n"


@pytest.fixture
def registry() -> MarketplaceRegistry:
    return MarketplaceRegistry()


class TestPublish:
    def test_publish_template(self, registry):
        t = registry.publish("My Workflow", SAMPLE_YAML, author="alice", tags=["research"])
        assert t.template_id
        assert t.name == "My Workflow"
        assert t.author == "alice"
        assert t.tags == ["research"]

    def test_publish_defaults(self, registry):
        t = registry.publish("Basic", SAMPLE_YAML)
        assert t.category == "general"
        assert t.verified is False
        assert t.downloads == 0


class TestCRUD:
    def test_get_template(self, registry):
        t = registry.publish("WF", SAMPLE_YAML)
        retrieved = registry.get(t.template_id)
        assert retrieved is not None
        assert retrieved.name == "WF"

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None

    def test_delete_template(self, registry):
        t = registry.publish("WF", SAMPLE_YAML)
        assert registry.delete(t.template_id) is True
        assert registry.get(t.template_id) is None

    def test_delete_nonexistent(self, registry):
        assert registry.delete("nonexistent") is False

    def test_list_templates(self, registry):
        registry.publish("WF1", SAMPLE_YAML, category="research")
        registry.publish("WF2", SAMPLE_YAML, category="devops")
        assert len(registry.list_templates()) == 2

    def test_list_by_category(self, registry):
        registry.publish("WF1", SAMPLE_YAML, category="research")
        registry.publish("WF2", SAMPLE_YAML, category="devops")
        results = registry.list_templates(category="research")
        assert len(results) == 1
        assert results[0].name == "WF1"

    def test_list_by_tags(self, registry):
        registry.publish("WF1", SAMPLE_YAML, tags=["python", "ml"])
        registry.publish("WF2", SAMPLE_YAML, tags=["javascript"])
        results = registry.list_templates(tags=["python"])
        assert len(results) == 1

    def test_list_verified_only(self, registry):
        t1 = registry.publish("WF1", SAMPLE_YAML)
        t2 = registry.publish("WF2", SAMPLE_YAML)
        registry.verify(t1.template_id)
        results = registry.list_templates(verified_only=True)
        assert len(results) == 1
        assert results[0].template_id == t1.template_id


class TestMetrics:
    def test_update_metrics(self, registry):
        t = registry.publish("WF", SAMPLE_YAML)
        metrics = TemplateMetrics(
            avg_cost_usd=0.05,
            avg_duration_seconds=30.0,
            approval_rate=0.95,
            completion_rate=0.98,
            total_runs=50,
        )
        assert registry.update_metrics(t.template_id, metrics) is True
        retrieved = registry.get(t.template_id)
        assert retrieved.metrics.total_runs == 50
        assert retrieved.metrics.approval_rate == 0.95

    def test_verify_template(self, registry):
        t = registry.publish("WF", SAMPLE_YAML)
        assert registry.verify(t.template_id) is True
        retrieved = registry.get(t.template_id)
        assert retrieved.verified is True

    def test_increment_downloads(self, registry):
        t = registry.publish("WF", SAMPLE_YAML)
        registry.increment_downloads(t.template_id)
        registry.increment_downloads(t.template_id)
        retrieved = registry.get(t.template_id)
        assert retrieved.downloads == 2


class TestImportExport:
    def test_export_template(self, registry):
        t = registry.publish("WF", SAMPLE_YAML, author="alice", tags=["test"])
        exported = registry.export_template(t.template_id)
        assert exported is not None
        data = json.loads(exported)
        assert data["name"] == "WF"
        assert data["author"] == "alice"

    def test_export_nonexistent(self, registry):
        assert registry.export_template("nonexistent") is None

    def test_import_template(self, registry):
        t = registry.publish("Original", SAMPLE_YAML, author="bob")
        exported = registry.export_template(t.template_id)
        imported = registry.import_template(exported)
        assert imported.name == "Original"
        assert imported.template_id != t.template_id  # New ID

    def test_import_export_roundtrip(self, registry):
        t = registry.publish("RT", SAMPLE_YAML, tags=["a", "b"], category="devops")
        metrics = TemplateMetrics(avg_cost_usd=0.1, total_runs=10)
        registry.update_metrics(t.template_id, metrics)
        exported = registry.export_template(t.template_id)
        imported = registry.import_template(exported)
        assert imported.name == "RT"
        assert imported.category == "devops"
        assert imported.tags == ["a", "b"]


class TestSchemaRoundTrip:
    def test_template_serialization(self):
        t = MarketplaceTemplate(
            template_id="t1", name="test", workflow_yaml=SAMPLE_YAML,
            tags=["a"], metrics=TemplateMetrics(total_runs=5),
        )
        data = t.model_dump(mode="json")
        restored = MarketplaceTemplate.model_validate(data)
        assert restored.name == "test"
        assert restored.metrics.total_runs == 5

    def test_metrics_serialization(self):
        m = TemplateMetrics(avg_cost_usd=0.5, approval_rate=0.9)
        data = m.model_dump(mode="json")
        restored = TemplateMetrics.model_validate(data)
        assert restored.avg_cost_usd == 0.5
