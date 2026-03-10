"""Integration tests for team-based workflow orchestration.

Tests the full flow: YAML parsing → team expansion → verification → execution
with stub adapters.
"""

from __future__ import annotations

import yaml

import pytest

from agentos.kernel.team_expander import expand_teams
from agentos.schemas.workflow import WorkflowDefinition
from agentos.validation.workflow_verifier import WorkflowVerifier


TEAM_WORKFLOW_YAML = """
name: team_integration_test
version: "1.0"

budget:
  max_tokens: 100000
  max_cost_usd: 5.00

teams:
  research_team:
    manager: lead
    members:
      - analyst
      - writer
    description: "Conducts research and produces reports"
    human_input: true

agents:
  lead:
    adapter: tier2_claude_code
    role: "Research lead who coordinates the team"
  analyst:
    adapter: tier2_claude_code
    role: "Data analyst"
  writer:
    adapter: tier2_claude_code
    role: "Report writer"

tasks:
  brief:
    name: brief
    type: input_gate
    prompt: "Provide research brief"
  research:
    name: research
    type: agent_task
    agent: lead
    description: "Lead coordinates research team"
    depends_on: [brief]
  review:
    name: review
    type: approval_gate
    prompt: "Approve the research output"
    depends_on: [research]
"""

TWO_TEAM_YAML = """
name: two_team_test
version: "1.0"

teams:
  team_a:
    manager: mgr_a
    members: [worker_a]
    description: "Team A does analysis"
  team_b:
    manager: mgr_b
    members: [worker_b]
    description: "Team B writes reports"

channels:
  a_to_b:
    name: a_to_b
    mode: broadcast

agents:
  mgr_a:
    adapter: tier2_claude_code
    role: "Manager A"
  worker_a:
    adapter: tier2_claude_code
    role: "Worker A"
  mgr_b:
    adapter: tier2_claude_code
    role: "Manager B"
  worker_b:
    adapter: tier2_claude_code
    role: "Worker B"

tasks:
  task_a:
    name: task_a
    type: agent_task
    agent: mgr_a
    description: "Team A task"
    publishes_to: [a_to_b]
  task_b:
    name: task_b
    type: agent_task
    agent: mgr_b
    description: "Team B task"
    depends_on: [task_a]
    subscribes_to: [a_to_b]
"""


class TestTeamWorkflowParsing:
    """Test YAML parsing with team definitions."""

    def test_parse_team_workflow(self):
        raw = yaml.safe_load(TEAM_WORKFLOW_YAML)
        wf = WorkflowDefinition.model_validate(raw)
        assert "research_team" in wf.teams
        assert wf.teams["research_team"].manager == "lead"
        assert wf.teams["research_team"].members == ["analyst", "writer"]

    def test_parse_two_team_workflow(self):
        raw = yaml.safe_load(TWO_TEAM_YAML)
        wf = WorkflowDefinition.model_validate(raw)
        assert len(wf.teams) == 2
        assert "team_a" in wf.teams
        assert "team_b" in wf.teams


class TestTeamExpansionIntegration:
    """Test team expansion produces correct channels and tags."""

    def test_single_team_expansion(self):
        raw = yaml.safe_load(TEAM_WORKFLOW_YAML)
        wf = WorkflowDefinition.model_validate(raw)
        expanded = expand_teams(wf)

        # Team channel created
        assert "team_research_team" in expanded.channels

        # Agents tagged
        assert expanded.agents["lead"].team == "research_team"
        assert expanded.agents["analyst"].team == "research_team"
        assert expanded.agents["writer"].team == "research_team"

        # Manager adapter set
        assert expanded.agents["lead"].adapter == "manager"

    def test_two_team_expansion(self):
        raw = yaml.safe_load(TWO_TEAM_YAML)
        wf = WorkflowDefinition.model_validate(raw)
        expanded = expand_teams(wf)

        # Both team channels created
        assert "team_team_a" in expanded.channels
        assert "team_team_b" in expanded.channels

        # Existing channel preserved
        assert "a_to_b" in expanded.channels

        # Tags correct
        assert expanded.agents["mgr_a"].team == "team_a"
        assert expanded.agents["worker_a"].team == "team_a"
        assert expanded.agents["mgr_b"].team == "team_b"
        assert expanded.agents["worker_b"].team == "team_b"


class TestTeamVerification:
    """Test workflow verifier catches team issues."""

    def test_valid_team_passes(self):
        raw = yaml.safe_load(TEAM_WORKFLOW_YAML)
        wf = WorkflowDefinition.model_validate(raw)
        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert report.valid

    def test_undefined_manager_error(self):
        raw = yaml.safe_load(TEAM_WORKFLOW_YAML)
        raw["teams"]["research_team"]["manager"] = "nonexistent"
        wf = WorkflowDefinition.model_validate(raw)
        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert not report.valid
        codes = [e.code for e in report.errors]
        assert "team_manager_undefined" in codes

    def test_undefined_member_error(self):
        raw = yaml.safe_load(TEAM_WORKFLOW_YAML)
        raw["teams"]["research_team"]["members"].append("ghost")
        wf = WorkflowDefinition.model_validate(raw)
        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert not report.valid
        codes = [e.code for e in report.errors]
        assert "team_member_undefined" in codes

    def test_manager_is_member_error(self):
        raw = yaml.safe_load(TEAM_WORKFLOW_YAML)
        raw["teams"]["research_team"]["members"].append("lead")
        wf = WorkflowDefinition.model_validate(raw)
        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert not report.valid
        codes = [e.code for e in report.errors]
        assert "team_manager_is_member" in codes

    def test_agent_in_multiple_teams_error(self):
        raw = yaml.safe_load(TWO_TEAM_YAML)
        # Add worker_a to team_b as well
        raw["teams"]["team_b"]["members"].append("worker_a")
        wf = WorkflowDefinition.model_validate(raw)
        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert not report.valid
        codes = [e.code for e in report.errors]
        assert "agent_in_multiple_teams" in codes

    def test_two_team_valid(self):
        raw = yaml.safe_load(TWO_TEAM_YAML)
        wf = WorkflowDefinition.model_validate(raw)
        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert report.valid


class TestExampleWorkflowsParse:
    """Verify that new example YAML files parse and verify cleanly."""

    @pytest.mark.parametrize("yaml_file", [
        "examples/event_planning.yaml",
        "examples/market_research.yaml",
    ])
    def test_example_parses_and_verifies(self, yaml_file):
        from pathlib import Path

        path = Path(yaml_file)
        if not path.exists():
            pytest.skip(f"{yaml_file} not found")

        raw = yaml.safe_load(path.read_text())
        wf = WorkflowDefinition.model_validate(raw)
        assert len(wf.teams) > 0

        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        # May have warnings but should not have errors
        assert report.valid, f"Errors: {[e.message for e in report.errors]}"

    def test_hedge_fund_with_teams_parses(self):
        from pathlib import Path

        path = Path("examples/hedge_fund_full.yaml")
        if not path.exists():
            pytest.skip("hedge_fund_full.yaml not found")

        raw = yaml.safe_load(path.read_text())
        wf = WorkflowDefinition.model_validate(raw)
        assert len(wf.teams) >= 2

        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert report.valid, f"Errors: {[e.message for e in report.errors]}"
