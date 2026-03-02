"""Tests for TaskStateMachine."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.state_machine import TaskStateMachine
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskStatus


class TestValidTransitions:
    def test_pending_to_running(self, state_machine: TaskStateMachine) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)

    def test_running_to_succeeded(self, state_machine: TaskStateMachine) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)

    def test_running_to_failed(self, state_machine: TaskStateMachine) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.FAILED)

    def test_running_to_waiting(self, state_machine: TaskStateMachine) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.WAITING)

    def test_waiting_to_running(self, state_machine: TaskStateMachine) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.WAITING)
        state_machine.transition("t1", TaskStatus.WAITING, TaskStatus.RUNNING)


class TestFullLifecycle:
    def test_full_lifecycle_with_gate(
        self, state_machine: TaskStateMachine
    ) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.WAITING)
        state_machine.transition("t1", TaskStatus.WAITING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)

        assert state_machine.get_state("t1") == TaskStatus.SUCCEEDED


class TestInvalidTransitions:
    def test_invalid_pending_to_succeeded(
        self, state_machine: TaskStateMachine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid transition"):
            state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.SUCCEEDED)

    def test_invalid_failed_is_terminal(
        self, state_machine: TaskStateMachine
    ) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.FAILED)
        with pytest.raises(ValueError, match="Invalid transition"):
            state_machine.transition("t1", TaskStatus.FAILED, TaskStatus.RUNNING)

    def test_invalid_succeeded_is_terminal(
        self, state_machine: TaskStateMachine
    ) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
        with pytest.raises(ValueError, match="Invalid transition"):
            state_machine.transition("t1", TaskStatus.SUCCEEDED, TaskStatus.RUNNING)


class TestGetState:
    def test_get_state_default_pending(
        self, state_machine: TaskStateMachine
    ) -> None:
        assert state_machine.get_state("unknown-task") == TaskStatus.PENDING

    def test_get_state_derived_from_events(
        self, state_machine: TaskStateMachine
    ) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        assert state_machine.get_state("t1") == TaskStatus.RUNNING

        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
        assert state_machine.get_state("t1") == TaskStatus.SUCCEEDED

    def test_multiple_tasks_independent(
        self, state_machine: TaskStateMachine
    ) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t2", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)

        assert state_machine.get_state("t1") == TaskStatus.SUCCEEDED
        assert state_machine.get_state("t2") == TaskStatus.RUNNING


class TestEventEmission:
    def test_transition_emits_correct_event(
        self,
        event_log: SQLiteEventLog,
        state_machine: TaskStateMachine,
    ) -> None:
        state_machine.transition(
            "t1", TaskStatus.PENDING, TaskStatus.RUNNING, agent_id="agent-01"
        )

        events = event_log.query(
            workflow_id="test-wf",
            event_type=EventType.TASK_STATE_CHANGED,
        )
        assert len(events) == 1
        payload = events[0].payload
        assert payload["task_id"] == "t1"
        assert payload["from_state"] == "pending"
        assert payload["to_state"] == "running"
        assert payload["agent_id"] == "agent-01"

    def test_transition_increments_seq(
        self,
        event_log: SQLiteEventLog,
        state_machine: TaskStateMachine,
    ) -> None:
        state_machine.transition("t1", TaskStatus.PENDING, TaskStatus.RUNNING)
        state_machine.transition("t1", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)

        events = event_log.query(
            workflow_id="test-wf",
            event_type=EventType.TASK_STATE_CHANGED,
        )
        assert events[0].seq == 0
        assert events[1].seq == 1
