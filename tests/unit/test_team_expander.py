"""Unit tests for team expander — compile-time resolution of teams."""

from __future__ import annotations

import pytest

from agentos.kernel.team_expander import TeamExpansionError, expand_teams
from agentos.schemas.agent import AgentConfig
from agentos.schemas.channel import ChannelConfig, ChannelMode
from agentos.schemas.task import TaskConfig
from agentos.schemas.team import TeamConfig
from agentos.schemas.workflow import WorkflowDefinition


def _make_wf(**overrides) -> WorkflowDefinition:
    """Create a minimal workflow with defaults."""
    defaults = {
        "name": "test",
        "agents": {
            "manager1": AgentConfig(adapter="tier2_claude_code", role="Manager"),
            "worker1": AgentConfig(adapter="tier2_claude_code", role="Worker 1"),
            "worker2": AgentConfig(adapter="tier2_claude_code", role="Worker 2"),
        },
        "tasks": {
            "task1": TaskConfig(name="task1", agent="manager1"),
        },
    }
    defaults.update(overrides)
    return WorkflowDefinition(**defaults)


class TestExpandTeamsBasic:
    """Basic team expansion tests."""

    def test_no_teams_passthrough(self):
        wf = _make_wf()
        result = expand_teams(wf)
        assert result.teams == {}
        assert result.channels == {}

    def test_creates_team_channel(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="manager1", members=["worker1", "worker2"]),
        })
        result = expand_teams(wf)
        assert "team_alpha" in result.channels
        assert result.channels["team_alpha"].mode == ChannelMode.BROADCAST

    def test_custom_channel_name(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(
                manager="manager1", members=["worker1"],
                channel="my_channel",
            ),
        })
        result = expand_teams(wf)
        assert "my_channel" in result.channels
        assert result.teams["alpha"].channel == "my_channel"

    def test_tags_agents_with_team(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="manager1", members=["worker1", "worker2"]),
        })
        result = expand_teams(wf)
        assert result.agents["manager1"].team == "alpha"
        assert result.agents["worker1"].team == "alpha"
        assert result.agents["worker2"].team == "alpha"

    def test_sets_manager_adapter(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="manager1", members=["worker1"]),
        })
        result = expand_teams(wf)
        assert result.agents["manager1"].adapter == "manager"

    def test_does_not_mutate_original(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="manager1", members=["worker1"]),
        })
        original_adapter = wf.agents["manager1"].adapter
        expand_teams(wf)
        assert wf.agents["manager1"].adapter == original_adapter
        assert wf.agents["manager1"].team is None

    def test_preserves_existing_channels(self):
        wf = _make_wf(
            teams={
                "alpha": TeamConfig(manager="manager1", members=["worker1"]),
            },
            channels={
                "existing": ChannelConfig(name="existing"),
            },
        )
        result = expand_teams(wf)
        assert "existing" in result.channels
        assert "team_alpha" in result.channels


class TestExpandTeamsValidation:
    """Validation error tests."""

    def test_manager_not_in_agents(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="nonexistent", members=["worker1"]),
        })
        with pytest.raises(TeamExpansionError, match="manager.*nonexistent.*not defined"):
            expand_teams(wf)

    def test_member_not_in_agents(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="manager1", members=["nonexistent"]),
        })
        with pytest.raises(TeamExpansionError, match="member.*nonexistent.*not defined"):
            expand_teams(wf)

    def test_manager_also_member(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="manager1", members=["manager1", "worker1"]),
        })
        with pytest.raises(TeamExpansionError, match="manager.*should not also be.*member"):
            expand_teams(wf)

    def test_agent_in_multiple_teams(self):
        wf = _make_wf(
            agents={
                "mgr1": AgentConfig(adapter="tier2_claude_code"),
                "mgr2": AgentConfig(adapter="tier2_claude_code"),
                "shared": AgentConfig(adapter="tier2_claude_code"),
            },
            teams={
                "alpha": TeamConfig(manager="mgr1", members=["shared"]),
                "beta": TeamConfig(manager="mgr2", members=["shared"]),
            },
        )
        with pytest.raises(TeamExpansionError, match="shared.*already belongs"):
            expand_teams(wf)


class TestExpandTeamsMultipleTeams:
    """Tests with multiple teams."""

    def test_two_teams(self):
        wf = _make_wf(
            agents={
                "mgr1": AgentConfig(adapter="tier2_claude_code"),
                "mgr2": AgentConfig(adapter="tier2_claude_code"),
                "w1": AgentConfig(adapter="tier2_claude_code"),
                "w2": AgentConfig(adapter="tier2_claude_code"),
            },
            teams={
                "team_a": TeamConfig(manager="mgr1", members=["w1"]),
                "team_b": TeamConfig(manager="mgr2", members=["w2"]),
            },
        )
        result = expand_teams(wf)
        assert result.agents["mgr1"].team == "team_a"
        assert result.agents["w1"].team == "team_a"
        assert result.agents["mgr2"].team == "team_b"
        assert result.agents["w2"].team == "team_b"
        assert "team_team_a" in result.channels
        assert "team_team_b" in result.channels


class TestExpandTeamsWorkspaceAndBudget:
    """Tests for workspace and budget resolution during expansion."""

    def test_resolves_default_workspace(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(manager="manager1", members=["worker1"]),
        })
        result = expand_teams(wf)
        assert result.teams["alpha"].workspace == "team_alpha"

    def test_preserves_custom_workspace(self):
        wf = _make_wf(teams={
            "alpha": TeamConfig(
                manager="manager1", members=["worker1"],
                workspace="custom_ws",
            ),
        })
        result = expand_teams(wf)
        assert result.teams["alpha"].workspace == "custom_ws"

    def test_budget_preserved(self):
        from agentos.schemas.budget import BudgetSpec

        wf = _make_wf(teams={
            "alpha": TeamConfig(
                manager="manager1", members=["worker1"],
                budget=BudgetSpec(max_tokens=50000, max_cost_usd=3.0),
            ),
        })
        result = expand_teams(wf)
        assert result.teams["alpha"].budget.max_tokens == 50000
        assert result.teams["alpha"].budget.max_cost_usd == 3.0


class TestTeamBudgetEnforcement:
    """Tests for team-level budget enforcement in BudgetManager."""

    def test_team_budget_exceeded(self):
        from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
        from agentos.kernel.event_log import SQLiteEventLog
        from agentos.kernel.seq import SeqCounter
        from agentos.schemas.budget import BudgetDelta, BudgetSpec

        event_log = SQLiteEventLog(":memory:")
        seq = SeqCounter()
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(),
            event_log=event_log,
            seq=seq,
            workflow_id="test",
            team_specs={"alpha": BudgetSpec(max_tokens=1000)},
            agent_teams={"w1": "alpha", "w2": "alpha"},
        )
        mgr.apply("w1", BudgetDelta(tokens=600))
        # w2 pushes team total to 1200 > 1000
        with pytest.raises(BudgetExceededError):
            mgr.apply("w2", BudgetDelta(tokens=600))

    def test_team_budget_within_limit(self):
        from agentos.kernel.budget_manager import BudgetManager
        from agentos.kernel.event_log import SQLiteEventLog
        from agentos.kernel.seq import SeqCounter
        from agentos.schemas.budget import BudgetDelta, BudgetSpec

        event_log = SQLiteEventLog(":memory:")
        seq = SeqCounter()
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(),
            event_log=event_log,
            seq=seq,
            workflow_id="test",
            team_specs={"alpha": BudgetSpec(max_tokens=2000)},
            agent_teams={"w1": "alpha", "w2": "alpha"},
        )
        mgr.apply("w1", BudgetDelta(tokens=600))
        mgr.apply("w2", BudgetDelta(tokens=600))
        team_usage = mgr.team_usage("alpha")
        assert team_usage.tokens_used == 1200

    def test_team_usage_aggregation(self):
        from agentos.kernel.budget_manager import BudgetManager
        from agentos.kernel.event_log import SQLiteEventLog
        from agentos.kernel.seq import SeqCounter
        from agentos.schemas.budget import BudgetDelta, BudgetSpec

        event_log = SQLiteEventLog(":memory:")
        seq = SeqCounter()
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(),
            event_log=event_log,
            seq=seq,
            workflow_id="test",
            agent_teams={"w1": "alpha", "w2": "alpha", "w3": "beta"},
        )
        mgr.apply("w1", BudgetDelta(tokens=100, cost_usd=0.5))
        mgr.apply("w2", BudgetDelta(tokens=200, cost_usd=1.0))
        mgr.apply("w3", BudgetDelta(tokens=300, cost_usd=1.5))

        alpha_usage = mgr.team_usage("alpha")
        assert alpha_usage.tokens_used == 300
        assert alpha_usage.cost_usd == 1.5

        beta_usage = mgr.team_usage("beta")
        assert beta_usage.tokens_used == 300
        assert beta_usage.cost_usd == 1.5
