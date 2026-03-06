"""Shared helpers for Tier 2 adapters (Claude Code, Aider, etc.).

Extracted from tier2_claude_code.py — prompt building, predecessor context,
manifest parsing, and manifest-to-TaskOutput conversion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskMetrics,
    TaskOutput,
    TaskStatus,
)

# Maximum retries when manifest.json is missing or invalid.
MAX_MANIFEST_RETRIES = 2

# Default timeout for a single Tier 2 invocation (seconds).
DEFAULT_TIMEOUT = 300


def build_prompt(
    task_description: str,
    role: str,
    predecessor_context: list[TaskOutput],
    workspace_files: list[str] | None = None,
) -> str:
    """Assemble the full prompt sent to a Tier 2 agent."""
    parts = []

    if role:
        parts.append(f"## Role\n{role}")

    parts.append(f"## Task\n{task_description}")

    if predecessor_context:
        parts.append("## Predecessor task outputs")
        for ctx in predecessor_context:
            parts.append(f"### Task: {ctx.task_id}")
            parts.append(f"Status: {ctx.status}")
            parts.append(f"Summary: {ctx.summary}")
            if ctx.key_findings:
                parts.append("Findings:")
                for f in ctx.key_findings:
                    parts.append(f"  - [{f.confidence}] {f.finding}")
            if ctx.open_questions:
                parts.append("Open questions:")
                for q in ctx.open_questions:
                    parts.append(f"  - {q}")
            parts.append("")

    if workspace_files:
        parts.append("## Available files in workspace")
        parts.append("These files are available for you to read:")
        for f in workspace_files[:50]:
            parts.append(f"  - {f}")

    parts.append(
        "## Output requirement\n"
        "When you are done, create a file called `manifest.json` in the "
        "current directory with this exact JSON structure:\n"
        "```json\n"
        "{\n"
        '  "summary": "1-3 sentence summary of what you accomplished",\n'
        '  "findings": [\n'
        '    {"finding": "what you found", "confidence": "high|medium|low", '
        '"sources": ["optional source refs"]}\n'
        "  ],\n"
        '  "open_questions": ["any unresolved questions"],\n'
        '  "files_produced": ["list of files you created or modified"]\n'
        "}\n"
        "```\n"
        "This manifest is REQUIRED. Do not skip it."
    )

    return "\n\n".join(parts)


def write_predecessor_context(workspace: Path, predecessors: list[TaskOutput]) -> None:
    """Write predecessor TaskOutput manifests to workspace for reference."""
    if not predecessors:
        return
    ctx_dir = workspace / ".agentos_context"
    ctx_dir.mkdir(exist_ok=True)
    for ctx in predecessors:
        path = ctx_dir / f"{ctx.task_id}.json"
        path.write_text(ctx.model_dump_json(indent=2))


def parse_manifest(workspace: Path) -> dict[str, Any] | None:
    """Read and parse manifest.json from the workspace.

    Returns None if the file doesn't exist or is invalid JSON.
    """
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def manifest_to_task_output(
    manifest: dict[str, Any],
    task_id: str,
    agent_id: str,
    metrics: TaskMetrics,
) -> TaskOutput:
    """Convert a parsed manifest dict to a TaskOutput."""
    findings = []
    for f in manifest.get("findings", []):
        if isinstance(f, dict):
            findings.append(Finding(
                finding=f.get("finding", ""),
                confidence=Confidence(f.get("confidence", "medium")),
                sources=f.get("sources", []),
            ))

    return TaskOutput(
        task_id=task_id,
        agent_id=agent_id,
        status=TaskStatus.SUCCEEDED,
        summary=manifest.get("summary", "Task completed."),
        key_findings=findings,
        open_questions=manifest.get("open_questions", []),
        metrics=metrics,
    )
