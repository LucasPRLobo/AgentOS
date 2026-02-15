"""NL workflow generator — creates WorkflowDefinitions from natural language."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Callable

from agentos.core.identifiers import generate_run_id
from agentos.lm.provider import BaseLMProvider, LMMessage
from agentos.runtime.domain_registry import DomainRegistry
from agentos.schemas.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a workflow generator for the AgentOS platform.  Given a natural
language description of what the user wants, you produce a **valid JSON**
WorkflowDefinition that can be loaded into the visual workflow builder.

## Rules

1. Each node is an autonomous agent with a role, an LLM model, a system
   prompt, and a set of tools.
2. Edges define data flow / execution order (DAG — no cycles).
3. Pick a reasonable model for each agent.  Default to "gpt-4o-mini" for
   cost-efficiency.  Use "gpt-4o" only when the task genuinely needs it.
4. Assign only the tools each agent actually needs.
5. Keep the team small — 2-5 agents is typical.
6. Give each node a short, unique ``id`` (snake_case) and a human-readable
   ``display_name``.
7. Write clear, specific ``system_prompt``s that tell each agent exactly what
   to do and what files to produce.
8. Include sensible ``budget`` limits for each node.

## Available Tools

{tool_list}

## Output Format

Return a **single JSON object** with two keys:
- ``"workflow"``: a complete WorkflowDefinition object (see schema below)
- ``"explanation"``: a 1-3 sentence explanation of the design

### WorkflowDefinition Schema (abbreviated)

```json
{{
  "id": "<generated>",
  "name": "Short name",
  "description": "What this workflow does",
  "version": "1.0.0",
  "domain_pack": "codeos",
  "nodes": [
    {{
      "id": "node_id",
      "role": "custom",
      "display_name": "Human Name",
      "position": {{"x": 100, "y": 100}},
      "config": {{
        "model": "gpt-4o-mini",
        "system_prompt": "...",
        "persona_preset": "analytical",
        "tools": ["tool_name"],
        "budget": {{
          "max_tokens": 15000,
          "max_tool_calls": 10,
          "max_time_seconds": 90.0,
          "max_recursion_depth": 1
        }},
        "max_steps": 15,
        "advanced": null
      }}
    }}
  ],
  "edges": [{{"source": "a", "target": "b"}}],
  "variables": [],
  "template_source": null
}}
```

Return **only** the JSON object.  No markdown fences, no extra text.
"""


def _format_tool_list(registry: DomainRegistry) -> str:
    """Build a concise tool catalogue from all registered packs."""
    lines: list[str] = []
    seen: set[str] = set()
    for pack in registry.list_packs():
        for tool in pack.tools:
            if tool.name in seen:
                continue
            seen.add(tool.name)
            lines.append(f"- **{tool.name}** ({tool.side_effect}): {tool.description}")
    return "\n".join(lines) if lines else "(no tools registered)"


class WorkflowGenerator:
    """Generate a WorkflowDefinition from a natural language description.

    Uses an LLM to translate the user's intent into a structured workflow
    JSON that can be opened in the visual builder.
    """

    def __init__(
        self,
        provider_factory: Callable[[str], BaseLMProvider],
        registry: DomainRegistry,
    ) -> None:
        self._factory = provider_factory
        self._registry = registry

    def generate(
        self,
        description: str,
        model: str = "gpt-4o-mini",
    ) -> tuple[WorkflowDefinition, str]:
        """Generate a workflow from *description* using *model*.

        Returns:
            A tuple of (WorkflowDefinition, explanation_string).

        Raises:
            ValueError: If the LLM output cannot be parsed.
            RuntimeError: If the LLM provider is unavailable.
        """
        provider = self._factory(model)

        tool_list = _format_tool_list(self._registry)
        system = _SYSTEM_PROMPT.format(tool_list=tool_list)

        messages = [
            LMMessage(role="system", content=system),
            LMMessage(role="user", content=description),
        ]

        response = provider.complete(messages)
        raw = response.content.strip()

        # Strip markdown code fences if the model wraps them
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}\n\nRaw:\n{raw[:500]}")

        # Handle both {"workflow": {...}, "explanation": "..."} and bare workflow
        if "workflow" in parsed and "explanation" in parsed:
            wf_data = parsed["workflow"]
            explanation = parsed["explanation"]
        else:
            wf_data = parsed
            explanation = ""

        # Inject generated ID and timestamps
        now = datetime.now(UTC).isoformat()
        wf_data.setdefault("id", str(generate_run_id()))
        wf_data.setdefault("created_at", now)
        wf_data.setdefault("updated_at", now)
        wf_data.setdefault("domain_pack", "codeos")
        wf_data.setdefault("version", "1.0.0")

        # Layout positions if missing — spread nodes horizontally
        for i, node in enumerate(wf_data.get("nodes", [])):
            if "position" not in node or node["position"] == {"x": 0, "y": 0}:
                node["position"] = {"x": 100 + i * 300, "y": 100}

        workflow = WorkflowDefinition.model_validate(wf_data)
        return workflow, explanation
