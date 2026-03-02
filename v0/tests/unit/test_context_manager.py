"""Tests for the context window manager."""

import pytest

from agentos.lm.context_manager import ContextManager
from agentos.lm.provider import LMMessage, ModelCapabilities


@pytest.fixture()
def caps() -> ModelCapabilities:
    return ModelCapabilities(
        context_window=8192,
        max_output_tokens=2048,
        provider="openai",
        display_name="Test Model",
    )


@pytest.fixture()
def mgr(caps: ModelCapabilities) -> ContextManager:
    return ContextManager("test-model", caps)


class TestContextManager:
    def test_context_budget(self, mgr: ContextManager, caps: ModelCapabilities) -> None:
        # Budget = context_window - output_reserve
        assert mgr.context_budget > 0
        assert mgr.context_budget < caps.context_window
        assert mgr.output_reserve > 0

    def test_estimate_tokens_heuristic(self, mgr: ContextManager) -> None:
        # ~4 chars per token
        tokens = mgr.estimate_tokens("Hello world!")  # 12 chars
        assert 2 <= tokens <= 5

    def test_estimate_tokens_empty(self, mgr: ContextManager) -> None:
        assert mgr.estimate_tokens("") >= 0

    def test_estimate_messages_tokens(self, mgr: ContextManager) -> None:
        msgs = [
            LMMessage(role="user", content="Hello"),
            LMMessage(role="assistant", content="Hi there!"),
        ]
        tokens = mgr.estimate_messages_tokens(msgs)
        assert tokens > 0

    def test_available_tokens(self, mgr: ContextManager) -> None:
        avail = mgr.available_tokens("You are a helpful assistant.")
        assert avail > 0
        assert avail < mgr.context_budget

    def test_available_tokens_with_tools(self, mgr: ContextManager) -> None:
        tools = [{"name": "search", "description": "Search the web"}]
        avail_no_tools = mgr.available_tokens("System prompt")
        avail_with_tools = mgr.available_tokens("System prompt", tool_schemas=tools)
        assert avail_with_tools < avail_no_tools


class TestBuildPrompt:
    def test_minimal_prompt(self, mgr: ContextManager) -> None:
        messages = mgr.build_prompt("You are a helpful agent.")
        assert len(messages) == 1
        assert messages[0].role == "system"
        assert "helpful agent" in messages[0].content

    def test_with_upstream(self, mgr: ContextManager) -> None:
        messages = mgr.build_prompt(
            "You are an agent.",
            upstream_output="Previous agent found: key results here.",
        )
        assert len(messages) == 2
        assert messages[0].role == "system"
        upstream_msg = messages[1]
        assert "previous agent" in upstream_msg.content.lower()

    def test_with_history(self, mgr: ContextManager) -> None:
        history = [
            LMMessage(role="user", content="What is AI?"),
            LMMessage(role="assistant", content="AI is artificial intelligence."),
        ]
        messages = mgr.build_prompt(
            "You are an agent.",
            conversation_history=history,
        )
        # System + 2 history messages
        assert len(messages) == 3

    def test_with_memory(self, mgr: ContextManager) -> None:
        messages = mgr.build_prompt(
            "You are an agent.",
            memory_context="User prefers concise answers.",
        )
        assert len(messages) == 2
        assert "memory" in messages[1].content.lower()

    def test_history_sliding_window(self, mgr: ContextManager) -> None:
        """Long history should be trimmed (oldest dropped)."""
        history = [
            LMMessage(role="user", content=f"Message {i}: {'x' * 500}")
            for i in range(100)
        ]
        messages = mgr.build_prompt(
            "You are an agent.",
            conversation_history=history,
        )
        # Should include system + some history, but not all 100
        assert len(messages) < 102
        # Most recent messages should be preserved
        last_content = messages[-1].content
        # The last message should be from the end of the history
        assert "Message 99" in last_content or "Message 98" in last_content

    def test_tools_in_system_prompt(self, mgr: ContextManager) -> None:
        tools = [{"name": "search", "description": "Search"}]
        messages = mgr.build_prompt(
            "Agent prompt",
            tool_schemas=tools,
        )
        assert "search" in messages[0].content.lower()

    def test_all_components(self, mgr: ContextManager) -> None:
        messages = mgr.build_prompt(
            "You are an agent.",
            tool_schemas=[{"name": "tool1"}],
            upstream_output="Data from upstream.",
            conversation_history=[
                LMMessage(role="user", content="Do the task."),
            ],
            memory_context="Important context.",
        )
        # system + memory + upstream + history
        assert len(messages) >= 3
        roles = [m.role for m in messages]
        assert roles[0] == "system"
