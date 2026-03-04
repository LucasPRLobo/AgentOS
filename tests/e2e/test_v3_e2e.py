"""V3+ end-to-end tests — specialization, fine-tuning, compliance templates."""

from __future__ import annotations

import json
import uuid

import pytest

from agentos.intelligence.finetune import (
    ExportConfig,
    ExportFormat,
    FineTuneExporter,
    TaskRecord,
)
from agentos.intelligence.knowledge_graph import SQLiteKnowledgeGraph
from agentos.intelligence.learning import (
    ConfigRecommender,
    PatternDetector,
    WorkflowRecord,
)
from agentos.intelligence.specialization import (
    PerformanceRecord,
    SpecializationTracker,
)
from agentos.kernel.memory_store import SQLiteMemoryStore, extract_memories_from_output
from agentos.kernel.mutable_dag import MutableDAG
from agentos.kernel.team_composer import TeamComposer
from agentos.marketplace.registry import MarketplaceRegistry
from agentos.schemas.memory import MemoryConfig, MemoryQuery
from agentos.schemas.spawn import AgentArchetype, SpawnPolicy


class TestSpecializationE2E:
    """Specialization shows measurable improvement across workflows."""

    def test_specialization_improves_over_runs(self):
        tracker = SpecializationTracker()

        # Simulate 10 workflows — agent improves over time
        for i in range(10):
            quality = 0.5 + (i * 0.05)  # Improves from 0.5 to 0.95
            tracker.record_performance(PerformanceRecord(
                agent_id="agent-alpha",
                role="researcher",
                workflow_id=f"wf-{i}",
                quality_score=min(quality, 1.0),
                cost_usd=0.05,
                duration_seconds=30.0,
                success=quality > 0.6,
            ))
            if i >= 5:
                tracker.add_feedback("agent-alpha", "researcher", f"Iteration {i}: good improvement")

        scores = tracker.get_specialization_scores()
        assert len(scores) == 1
        assert scores[0].avg_quality > 0.7
        assert scores[0].sample_size == 10

        # Prompt refinement should include recent feedback
        refinement = tracker.refine_prompt("agent-alpha", "researcher", "You are a researcher.")
        assert refinement.feedback_count >= 5
        assert "good improvement" in refinement.refined_prompt

    def test_best_agent_selection(self):
        tracker = SpecializationTracker()

        # Two agents, one better at research
        for i in range(5):
            tracker.record_performance(PerformanceRecord(
                agent_id="specialist", role="researcher",
                workflow_id=f"s-{i}", quality_score=0.95,
                cost_usd=0.1, duration_seconds=20.0, success=True,
            ))
            tracker.record_performance(PerformanceRecord(
                agent_id="generalist", role="researcher",
                workflow_id=f"g-{i}", quality_score=0.6,
                cost_usd=0.05, duration_seconds=40.0, success=True,
            ))

        best = tracker.get_best_agent_for_role("researcher")
        assert best == "specialist"


class TestFineTuningFromWorkflows:
    """Fine-tuning export produces valid training data from 10+ workflows."""

    def test_export_from_10_workflows(self):
        exporter = FineTuneExporter()

        for i in range(12):
            exporter.add_record(TaskRecord(
                task_id=f"t-{i}",
                workflow_id=f"wf-{i}",
                system_prompt="You are an expert analyst.",
                user_input=f"Analyze dataset #{i}",
                assistant_output=f"Analysis complete for dataset #{i}. Key finding: trend {i}.",
                quality_score=0.8 + (i % 3) * 0.05,
                approved=i != 5,  # One rejected
            ))

        # Export OpenAI format
        openai_result = exporter.export(ExportConfig(format=ExportFormat.JSONL_OPENAI))
        assert openai_result.exported >= 10
        assert openai_result.filtered_approval == 1

        # Verify each line is valid JSONL
        for line in openai_result.lines:
            data = json.loads(line)
            assert len(data["messages"]) == 3

        # Export Anthropic format
        anthropic_result = exporter.export(ExportConfig(format=ExportFormat.JSONL_ANTHROPIC))
        assert anthropic_result.exported == openai_result.exported

        for line in anthropic_result.lines:
            data = json.loads(line)
            assert "system" in data


class TestVerticalComplianceTemplates:
    """Compliance package templates for financial, healthcare, legal verticals."""

    @pytest.fixture
    def registry(self):
        return MarketplaceRegistry()

    def test_financial_compliance_template(self, registry):
        yaml_str = """
name: financial-audit
version: '1.0'
agents:
  auditor:
    adapter: tier1
    model: claude-sonnet-4-20250514
    role: Financial compliance auditor
tasks:
  review_transactions:
    name: review_transactions
    agent: auditor
    description: Review transactions for regulatory compliance
  generate_report:
    name: generate_report
    agent: auditor
    description: Generate compliance report
    depends_on: [review_transactions]
"""
        t = registry.publish("Financial Audit", yaml_str, category="finance",
                           tags=["compliance", "audit", "financial"])
        registry.verify(t.template_id)
        retrieved = registry.get(t.template_id)
        assert retrieved.verified
        assert "compliance" in retrieved.tags

    def test_healthcare_compliance_template(self, registry):
        yaml_str = """
name: hipaa-review
version: '1.0'
agents:
  reviewer:
    adapter: tier1
    model: claude-sonnet-4-20250514
    role: HIPAA compliance reviewer
tasks:
  scan_data:
    name: scan_data
    agent: reviewer
    description: Scan data handling for HIPAA compliance
  assess_risk:
    name: assess_risk
    agent: reviewer
    description: Assess privacy risk
    depends_on: [scan_data]
"""
        t = registry.publish("HIPAA Review", yaml_str, category="healthcare",
                           tags=["compliance", "hipaa", "healthcare"])
        assert t.category == "healthcare"

    def test_legal_compliance_template(self, registry):
        yaml_str = """
name: contract-review
version: '1.0'
agents:
  analyst:
    adapter: tier1
    model: claude-sonnet-4-20250514
    role: Legal document analyst
tasks:
  extract_clauses:
    name: extract_clauses
    agent: analyst
    description: Extract key clauses from contracts
  flag_risks:
    name: flag_risks
    agent: analyst
    description: Flag high-risk clauses
    depends_on: [extract_clauses]
"""
        t = registry.publish("Contract Review", yaml_str, category="legal",
                           tags=["compliance", "legal", "contracts"])
        assert t.category == "legal"

    def test_all_verticals_in_marketplace(self, registry):
        for cat, name in [("finance", "FIN"), ("healthcare", "HC"), ("legal", "LEG")]:
            registry.publish(name, "name: x\nversion: '1.0'\nagents: {}\ntasks: {}\n",
                           category=cat, tags=["compliance"])

        all_templates = registry.list_templates()
        assert len(all_templates) == 3
        categories = {t.category for t in all_templates}
        assert categories == {"finance", "healthcare", "legal"}


class TestFullSystemIntegration:
    """Complete system test: all V2/V3 components working together."""

    def test_full_pipeline(self):
        # 1. Knowledge graph accumulates across runs
        kg = SQLiteKnowledgeGraph()
        for i in range(3):
            e = kg.add_entity("run_result", f"Result {i}", source_workflow=f"wf-{i}")
            kg.add_observation(e.entity_id, f"Observation from run {i}")
        assert kg.entity_count() == 3

        # 2. Cross-run memory stores findings
        store = SQLiteMemoryStore(MemoryConfig(enabled=True))
        for i in range(3):
            memories = extract_memories_from_output(
                f"wf-{i}", f"t-{i}",
                [{"content": f"Finding {i}", "confidence": 0.9}],
            )
            for m in memories:
                store.store(m)
        assert store.count() == 3

        # 3. Learning detects patterns
        detector = PatternDetector()
        for i in range(5):
            detector.add_record(WorkflowRecord(
                workflow_id=f"wf-{i}", workflow_name="test",
                team_composition=["agent-a", "agent-b"],
                total_cost_usd=0.1, total_duration_seconds=30.0,
                quality_score=0.8, success=True,
            ))

        # 4. Specialization tracks performance
        tracker = SpecializationTracker()
        for i in range(5):
            tracker.record_performance(PerformanceRecord(
                agent_id="agent-a", role="researcher",
                workflow_id=f"wf-{i}", quality_score=0.85,
                cost_usd=0.05, duration_seconds=25.0, success=True,
            ))

        # 5. Marketplace has templates
        marketplace = MarketplaceRegistry()
        marketplace.publish("Test WF", "name: t\nversion: '1.0'\nagents: {}\ntasks: {}\n")

        # Verify everything works
        assert kg.entity_count() >= 3
        assert store.count() >= 3
        scores = tracker.get_specialization_scores()
        assert len(scores) >= 1
        assert len(marketplace.list_templates()) >= 1
