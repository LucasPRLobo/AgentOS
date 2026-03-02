"""Unit tests for NL workflow generator."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.domain_registry import (
    DomainPackManifest,
    DomainRegistry,
    ToolManifestEntry,
)
from agentplatform.nl_generator import WorkflowGenerator, _format_tool_list


# ── Helpers ────────────────────────────────────────────────────────


class MockProvider(BaseLMProvider):
    """LM provider that returns a canned JSON response."""

    def __init__(self, response_json: dict) -> None:
        self._json = response_json

    @property
    def name(self) -> str:
        return "mock"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        return LMResponse(
            content=json.dumps(self._json),
            tokens_used=100,
            prompt_tokens=80,
            completion_tokens=20,
        )


def _make_registry() -> DomainRegistry:
    """Build a minimal DomainRegistry with a couple of tools."""
    reg = DomainRegistry()
    reg.register(DomainPackManifest(
        name="test",
        display_name="Test Pack",
        description="Test",
        version="0.1.0",
        tools=[
            ToolManifestEntry(name="file_read", description="Read a file", side_effect="READ", factory="x:X"),
            ToolManifestEntry(name="file_write", description="Write a file", side_effect="WRITE", factory="x:X"),
            ToolManifestEntry(name="web_search", description="Search web", side_effect="READ", factory="x:X"),
        ],
        role_templates=[],
        workflows=[],
    ))
    return reg


_VALID_WORKFLOW = {
    "workflow": {
        "name": "Test Workflow",
        "description": "A test workflow",
        "domain_pack": "codeos",
        "nodes": [
            {
                "id": "researcher",
                "role": "custom",
                "display_name": "Researcher",
                "position": {"x": 100, "y": 100},
                "config": {
                    "model": "gpt-4o-mini",
                    "system_prompt": "Research things.",
                    "persona_preset": "analytical",
                    "tools": ["web_search", "file_write"],
                    "budget": None,
                    "max_steps": 15,
                    "advanced": None,
                },
            },
            {
                "id": "writer",
                "role": "custom",
                "display_name": "Writer",
                "position": {"x": 400, "y": 100},
                "config": {
                    "model": "gpt-4o-mini",
                    "system_prompt": "Write a report.",
                    "persona_preset": "formal",
                    "tools": ["file_read", "file_write"],
                    "budget": None,
                    "max_steps": 10,
                    "advanced": None,
                },
            },
        ],
        "edges": [{"source": "researcher", "target": "writer"}],
        "variables": [],
    },
    "explanation": "Two agents: one researches, one writes.",
}


# ── Tests ──────────────────────────────────────────────────────────


class TestWorkflowGenerator:
    def test_generate_valid_workflow(self) -> None:
        provider = MockProvider(_VALID_WORKFLOW)
        registry = _make_registry()
        gen = WorkflowGenerator(
            provider_factory=lambda m: provider,
            registry=registry,
        )
        wf, explanation = gen.generate("Research X and write a report")
        assert wf.name == "Test Workflow"
        assert len(wf.nodes) == 2
        assert len(wf.edges) == 1
        assert explanation == "Two agents: one researches, one writes."

    def test_generate_bare_workflow_json(self) -> None:
        """When LLM returns just a workflow (no wrapper), it still works."""
        bare = _VALID_WORKFLOW["workflow"].copy()
        provider = MockProvider(bare)
        registry = _make_registry()
        gen = WorkflowGenerator(
            provider_factory=lambda m: provider,
            registry=registry,
        )
        wf, explanation = gen.generate("Do something")
        assert wf.name == "Test Workflow"
        assert explanation == ""

    def test_generate_strips_markdown_fences(self) -> None:
        """LLM may wrap JSON in ```json ... ``` fences."""

        class FencedProvider(BaseLMProvider):
            @property
            def name(self) -> str:
                return "fenced"

            def complete(self, messages: list[LMMessage]) -> LMResponse:
                raw = "```json\n" + json.dumps(_VALID_WORKFLOW) + "\n```"
                return LMResponse(content=raw, tokens_used=100)

        registry = _make_registry()
        gen = WorkflowGenerator(
            provider_factory=lambda m: FencedProvider(),
            registry=registry,
        )
        wf, explanation = gen.generate("Test fences")
        assert wf.name == "Test Workflow"

    def test_generate_invalid_json_raises(self) -> None:
        """LLM returns garbage → ValueError."""

        class BadProvider(BaseLMProvider):
            @property
            def name(self) -> str:
                return "bad"

            def complete(self, messages: list[LMMessage]) -> LMResponse:
                return LMResponse(content="not json at all", tokens_used=50)

        registry = _make_registry()
        gen = WorkflowGenerator(
            provider_factory=lambda m: BadProvider(),
            registry=registry,
        )
        with pytest.raises(ValueError, match="invalid JSON"):
            gen.generate("This should fail")

    def test_generate_auto_assigns_positions(self) -> None:
        """Nodes without positions get auto-placed."""
        data = {
            "workflow": {
                "name": "AutoPos",
                "description": "",
                "domain_pack": "codeos",
                "nodes": [
                    {
                        "id": "a",
                        "role": "custom",
                        "display_name": "A",
                        "position": {"x": 0, "y": 0},
                        "config": {
                            "model": "gpt-4o-mini",
                            "system_prompt": "A",
                            "persona_preset": "analytical",
                            "tools": [],
                            "budget": None,
                            "max_steps": 5,
                            "advanced": None,
                        },
                    },
                    {
                        "id": "b",
                        "role": "custom",
                        "display_name": "B",
                        "position": {"x": 0, "y": 0},
                        "config": {
                            "model": "gpt-4o-mini",
                            "system_prompt": "B",
                            "persona_preset": "analytical",
                            "tools": [],
                            "budget": None,
                            "max_steps": 5,
                            "advanced": None,
                        },
                    },
                ],
                "edges": [],
                "variables": [],
            },
            "explanation": "",
        }
        provider = MockProvider(data)
        registry = _make_registry()
        gen = WorkflowGenerator(
            provider_factory=lambda m: provider,
            registry=registry,
        )
        wf, _ = gen.generate("Two agents")
        # Nodes should have been auto-positioned (not both at 0,0)
        positions = [n.position for n in wf.nodes]
        assert positions[0]["x"] != positions[1]["x"]


class TestFormatToolList:
    def test_format_deduplicates(self) -> None:
        """Tools from multiple packs with same name appear once."""
        reg = DomainRegistry()
        reg.register(DomainPackManifest(
            name="p1", display_name="P1", description="", version="0.1.0",
            tools=[ToolManifestEntry(name="tool_a", description="Tool A", side_effect="READ", factory="x:X")],
            role_templates=[], workflows=[],
        ))
        reg.register(DomainPackManifest(
            name="p2", display_name="P2", description="", version="0.1.0",
            tools=[ToolManifestEntry(name="tool_a", description="Tool A", side_effect="READ", factory="x:X")],
            role_templates=[], workflows=[],
        ))
        result = _format_tool_list(reg)
        assert result.count("tool_a") == 1
