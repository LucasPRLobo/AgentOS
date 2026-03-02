"""Shared test fixtures for AgentOS."""

from __future__ import annotations

import pytest

from agentos.kernel.seq import SeqCounter


@pytest.fixture
def seq() -> SeqCounter:
    """Fresh SeqCounter starting at 0."""
    return SeqCounter()


@pytest.fixture
def seq_from_10() -> SeqCounter:
    """SeqCounter starting at 10 (simulates resumed workflow)."""
    return SeqCounter(start=10)
