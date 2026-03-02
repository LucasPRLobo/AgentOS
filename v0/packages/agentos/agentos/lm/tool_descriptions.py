"""Tool description builder — format tool schemas for LM system prompts."""

from __future__ import annotations

import json

from agentos.tools.registry import ToolRegistry


def build_tool_descriptions(registry: ToolRegistry) -> str:
    """Build a formatted string describing all tools in the registry.

    Returns a human-readable description suitable for inclusion in an LM
    system prompt. Each tool includes its name, side effect classification,
    and input/output JSON schemas.
    """
    tools = registry.list_tools()
    if not tools:
        return "No tools available."

    sections: list[str] = []
    for tool in tools:
        input_schema = json.dumps(
            tool.input_schema.model_json_schema(), indent=2, sort_keys=True
        )
        output_schema = json.dumps(
            tool.output_schema.model_json_schema(), indent=2, sort_keys=True
        )
        section = (
            f"## {tool.name} (v{tool.version})\n"
            f"Side effect: {tool.side_effect.value}\n"
            f"Input schema:\n```json\n{input_schema}\n```\n"
            f"Output schema:\n```json\n{output_schema}\n```"
        )
        sections.append(section)

    return "\n\n".join(sections)
