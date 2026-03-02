"""Shared test fixtures for AgentOS."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.kernel.state_machine import TaskStateMachine


@pytest.fixture
def seq() -> SeqCounter:
    """Fresh SeqCounter starting at 0."""
    return SeqCounter()


@pytest.fixture
def seq_from_10() -> SeqCounter:
    """SeqCounter starting at 10 (simulates resumed workflow)."""
    return SeqCounter(start=10)


@pytest.fixture
def event_log() -> SQLiteEventLog:
    """Fresh in-memory SQLiteEventLog."""
    return SQLiteEventLog(":memory:")


@pytest.fixture
def state_machine(event_log: SQLiteEventLog, seq: SeqCounter) -> TaskStateMachine:
    """TaskStateMachine wired to in-memory event_log and seq counter."""
    return TaskStateMachine(event_log=event_log, seq=seq, workflow_id="test-wf")
