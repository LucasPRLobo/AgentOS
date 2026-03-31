"""Tests for workspace schemas."""

from agentos.workspace.schemas import (
    ActivationContext,
    AgentContextSummary,
    BacklogTask,
    BacklogTaskStatus,
    CompletionResult,
    CoordinatorConfig,
    ParticipantRole,
    TeamMode,
    WorkspaceConfig,
    WorkspaceContextSummary,
    WorkspaceParticipant,
    WorkspaceState,
    WorkspaceStatus,
)


class TestWorkspaceConfig:
    def test_defaults(self):
        cfg = WorkspaceConfig(name="test", goal="do something")
        assert cfg.team_mode == TeamMode.SUGGEST
        assert cfg.coordinator.enabled is True
        assert cfg.coordinator.model == "opus"
        assert cfg.team == []
        assert cfg.persist is True

    def test_full_config(self):
        cfg = WorkspaceConfig(
            name="Investment",
            goal="Manage portfolio",
            team_mode=TeamMode.AUTO_FULL,
            team=[
                WorkspaceParticipant(name="analyst", specialization="Finance"),
                WorkspaceParticipant(name="lucas", type="human", roles=[ParticipantRole.LEAD]),
            ],
            acceptance_criteria=["Report produced"],
        )
        assert len(cfg.team) == 2
        assert cfg.team[1].type == "human"

    def test_roundtrip(self):
        cfg = WorkspaceConfig(name="t", goal="g")
        data = cfg.model_dump(mode="json")
        cfg2 = WorkspaceConfig(**data)
        assert cfg2.name == "t"


class TestBacklogTask:
    def test_defaults(self):
        t = BacklogTask(title="Research ECB")
        assert t.task_id
        assert t.status == BacklogTaskStatus.OPEN
        assert t.depends_on == []
        assert t.stall_count == 0

    def test_all_fields(self):
        t = BacklogTask(
            title="Analyze",
            description="Analyze data",
            depends_on=["task-1"],
            priority="high",
            model_tier="opus",
            estimated_minutes=20,
            next_task={"title": "Report"},
        )
        assert t.priority == "high"
        assert t.model_tier == "opus"
        assert t.next_task["title"] == "Report"


class TestAgentContextSummary:
    def test_defaults(self):
        s = AgentContextSummary(agent_id="a")
        assert s.intent == ""
        assert s.changes_made == []
        assert s.summary_version == 0

    def test_incremental_update(self):
        s = AgentContextSummary(agent_id="a", intent="Research")
        s.changes_made.append("Found GDP data")
        s.summary_version += 1
        assert s.summary_version == 1


class TestWorkspaceContextSummary:
    def test_defaults(self):
        s = WorkspaceContextSummary()
        assert s.tasks_completed == 0
        assert s.facts == []
        assert s.current_plan == []


class TestCompletionResult:
    def test_defaults(self):
        r = CompletionResult()
        assert r.complete is False
        assert r.layer == 0


class TestWorkspaceState:
    def test_creates(self):
        cfg = WorkspaceConfig(name="t", goal="g")
        s = WorkspaceState(config=cfg)
        assert s.status == WorkspaceStatus.ACTIVE


class TestActivationContext:
    def test_creates(self):
        task = BacklogTask(title="Test")
        ctx = ActivationContext(agent_id="a", task=task)
        assert ctx.agent_id == "a"
        assert ctx.predecessor_outputs == []
