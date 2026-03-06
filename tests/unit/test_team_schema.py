"""Unit tests for TeamConfig schema and WorkflowDefinition with teams."""

from __future__ import annotations

import pytest

from agentos.schemas.agent import AgentConfig
from agentos.schemas.team import TeamConfig
from agentos.schemas.workflow import WorkflowDefinition


class TestTeamConfig:
    """Tests for TeamConfig Pydantic model."""

    def test_minimal_team(self):
        team = TeamConfig(manager="boss")
        assert team.manager == "boss"
        assert team.members == []
        assert team.description == ""
        assert team.channel is None
        assert team.human_input is False
        assert team.budget.max_tokens is None
        assert team.workspace == ""

    def test_full_team(self):
        team = TeamConfig(
            manager="lead",
            members=["alice", "bob"],
            description="Research team",
            channel="team_research",
            human_input=True,
        )
        assert team.manager == "lead"
        assert team.members == ["alice", "bob"]
        assert team.description == "Research team"
        assert team.channel == "team_research"
        assert team.human_input is True

    def test_team_serialization(self):
        team = TeamConfig(manager="lead", members=["a", "b"])
        data = team.model_dump()
        assert data["manager"] == "lead"
        assert data["members"] == ["a", "b"]
        restored = TeamConfig.model_validate(data)
        assert restored == team


class TestWorkflowDefinitionWithTeams:
    """Tests for WorkflowDefinition.teams field."""

    def test_empty_teams_default(self):
        wf = WorkflowDefinition(name="test")
        assert wf.teams == {}

    def test_workflow_with_teams(self):
        wf = WorkflowDefinition(
            name="test",
            teams={
                "research": TeamConfig(
                    manager="lead",
                    members=["analyst1", "analyst2"],
                    description="Research team",
                ),
            },
        )
        assert "research" in wf.teams
        assert wf.teams["research"].manager == "lead"
        assert len(wf.teams["research"].members) == 2

    def test_workflow_teams_from_dict(self):
        """Test that teams can be parsed from raw dict (YAML input)."""
        raw = {
            "name": "test",
            "teams": {
                "team_a": {
                    "manager": "mgr",
                    "members": ["worker1"],
                    "human_input": True,
                },
            },
        }
        wf = WorkflowDefinition.model_validate(raw)
        assert wf.teams["team_a"].human_input is True
        assert wf.teams["team_a"].manager == "mgr"

    def test_backward_compat_no_teams(self):
        """Existing workflows without teams should still parse."""
        raw = {
            "name": "legacy",
            "agents": {"a1": {"adapter": "tier1"}},
            "tasks": {"t1": {"name": "t1", "agent": "a1"}},
        }
        wf = WorkflowDefinition.model_validate(raw)
        assert wf.teams == {}


class TestAgentConfigTeamField:
    """Tests for AgentConfig.team field."""

    def test_default_team_none(self):
        agent = AgentConfig()
        assert agent.team is None

    def test_agent_with_team(self):
        agent = AgentConfig(team="research")
        assert agent.team == "research"

    def test_agent_serialization_with_team(self):
        agent = AgentConfig(team="quant")
        data = agent.model_dump()
        assert data["team"] == "quant"
        restored = AgentConfig.model_validate(data)
        assert restored.team == "quant"


class TestTeamBudgetAndWorkspace:
    """Tests for team budget and workspace fields."""

    def test_team_with_budget(self):
        from agentos.schemas.budget import BudgetSpec

        team = TeamConfig(
            manager="lead",
            budget=BudgetSpec(max_tokens=100000, max_cost_usd=5.0),
        )
        assert team.budget.max_tokens == 100000
        assert team.budget.max_cost_usd == 5.0

    def test_team_budget_from_dict(self):
        raw = {
            "name": "test",
            "teams": {
                "t": {
                    "manager": "m",
                    "budget": {"max_tokens": 50000, "max_cost_usd": 2.0},
                },
            },
        }
        wf = WorkflowDefinition.model_validate(raw)
        assert wf.teams["t"].budget.max_tokens == 50000

    def test_team_with_workspace(self):
        team = TeamConfig(manager="lead", workspace="research_ws")
        assert team.workspace == "research_ws"

    def test_team_default_workspace_empty(self):
        team = TeamConfig(manager="lead")
        assert team.workspace == ""
