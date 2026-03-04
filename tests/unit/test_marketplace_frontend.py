"""Tests for marketplace frontend and intelligence E2E integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentos.intelligence.benchmark import BenchmarkRunner
from agentos.marketplace.registry import MarketplaceRegistry
from agentos.schemas.benchmark import BenchmarkConfig
from agentos.schemas.marketplace import TemplateMetrics

FRONTEND_SRC = Path(__file__).parent.parent.parent / "agentos" / "dashboard" / "frontend" / "src"
SAMPLE_YAML = "name: test\nversion: '1.0'\nagents: {}\ntasks: {}\n"


class TestMarketplaceFrontendExists:
    def test_marketplace_page_exists(self):
        path = FRONTEND_SRC / "pages" / "MarketplacePage.tsx"
        assert path.exists()
        content = path.read_text()
        assert "MarketplacePage" in content
        assert "template-grid" in content
        assert "deploy-btn" in content or "Deploy" in content

    def test_app_has_marketplace_route(self):
        content = (FRONTEND_SRC / "App.tsx").read_text()
        assert "/marketplace" in content
        assert "MarketplacePage" in content

    def test_marketplace_has_search(self):
        content = (FRONTEND_SRC / "pages" / "MarketplacePage.tsx").read_text()
        assert "marketplace-search" in content

    def test_marketplace_has_category_filter(self):
        content = (FRONTEND_SRC / "pages" / "MarketplacePage.tsx").read_text()
        assert "marketplace-category" in content

    def test_marketplace_has_verified_filter(self):
        content = (FRONTEND_SRC / "pages" / "MarketplacePage.tsx").read_text()
        assert "verified-filter" in content

    def test_marketplace_shows_metrics(self):
        content = (FRONTEND_SRC / "pages" / "MarketplacePage.tsx").read_text()
        assert "template-metrics" in content
        assert "avg_cost_usd" in content


class TestIntelligencePolish:
    """Verify benchmark + marketplace work together."""

    def test_benchmark_results_attach_to_template(self):
        registry = MarketplaceRegistry()
        t = registry.publish("Benchmark WF", SAMPLE_YAML)

        runner = BenchmarkRunner(BenchmarkConfig(backends=["a", "b"]))
        run = runner.create_run("Test task")
        runner.record_result(run.run_id, "a", 5.0, 1000, 0.10, "done", quality_score=0.8)
        runner.record_result(run.run_id, "b", 3.0, 800, 0.15, "done", quality_score=0.9)
        report = runner.generate_report(run.run_id)

        # Use benchmark results to update template metrics
        metrics = TemplateMetrics(
            avg_cost_usd=0.125,
            avg_duration_seconds=4.0,
            approval_rate=0.95,
            completion_rate=1.0,
            total_runs=2,
        )
        registry.update_metrics(t.template_id, metrics)

        retrieved = registry.get(t.template_id)
        assert retrieved.metrics.total_runs == 2
        assert retrieved.metrics.avg_cost_usd == 0.125

    def test_marketplace_with_multiple_templates_and_metrics(self):
        registry = MarketplaceRegistry()

        for i in range(5):
            t = registry.publish(
                f"Template {i}",
                SAMPLE_YAML,
                category="research" if i % 2 == 0 else "devops",
                tags=[f"tag-{i}"],
            )
            metrics = TemplateMetrics(
                avg_cost_usd=0.01 * (i + 1),
                total_runs=10 * (i + 1),
            )
            registry.update_metrics(t.template_id, metrics)
            if i % 2 == 0:
                registry.verify(t.template_id)

        all_templates = registry.list_templates()
        assert len(all_templates) == 5

        verified = registry.list_templates(verified_only=True)
        assert len(verified) == 3

        research = registry.list_templates(category="research")
        assert len(research) == 3

    def test_template_deploy_flow(self):
        """Simulate: user finds template → deploys → metrics update."""
        registry = MarketplaceRegistry()
        t = registry.publish("Deploy Test", SAMPLE_YAML, tags=["auto"])

        # Simulate deploy (increment download)
        registry.increment_downloads(t.template_id)
        retrieved = registry.get(t.template_id)
        assert retrieved.downloads == 1

        # After execution, update metrics
        metrics = TemplateMetrics(
            avg_cost_usd=0.05,
            avg_duration_seconds=15.0,
            completion_rate=1.0,
            total_runs=1,
        )
        registry.update_metrics(t.template_id, metrics)
        retrieved = registry.get(t.template_id)
        assert retrieved.metrics.total_runs == 1
