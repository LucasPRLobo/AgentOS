"""Shared helpers for Tier 2 adapters (Claude Code, Aider, etc.).

Extracted from tier2_claude_code.py — prompt building, predecessor context,
manifest parsing, and manifest-to-TaskOutput conversion.
"""

from __future__ import annotations

import json
import re
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


# ---------------------------------------------------------------------------
# Communication file helpers for Tier 2 workspace-based comms
# ---------------------------------------------------------------------------


def write_board_state(workspace: Path, board_manager: Any) -> None:
    """Write current board state to ``.agentos/board.md`` in the workspace.

    This gives Tier 2 subprocess agents a readable snapshot of the board
    before they start work.
    """
    comms_dir = workspace / ".agentos"
    comms_dir.mkdir(exist_ok=True)
    board_path = comms_dir / "board.md"

    state = board_manager.render_compact(max_tokens=400)
    board_path.write_text(state)


def write_inbox(workspace: Path, messages: list[Any]) -> None:
    """Write pending direct messages as individual files in ``.agentos/inbox/``.

    Each message becomes a markdown file the agent can read during execution.
    """
    inbox_dir = workspace / ".agentos" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale files
    for existing in inbox_dir.glob("msg-*.md"):
        existing.unlink()

    for msg in messages:
        path = inbox_dir / f"msg-{msg.message_id[:8]}.md"
        lines = [
            f"# Message from {msg.sender_id} ({msg.sender_type})",
            f"**Speech act:** {msg.speech_act}",
            f"**Priority:** {msg.priority}",
            f"**Time:** {msg.timestamp}",
            "",
            msg.content,
        ]
        if msg.speech_act == "request":
            lines.append("")
            lines.append(
                "> Response expected — write a reply file to `.agentos/outbox/`."
            )
        path.write_text("\n".join(lines))


def read_outbox(workspace: Path) -> list[dict[str, Any]]:
    """Read and parse outbox JSON files written by Tier 2 agents.

    Agents write JSON files to ``.agentos/outbox/`` to send messages.
    Expected format: ``{"to": "recipient", "content": "text", "speech_act": "inform"}``.
    Files are deleted after reading.
    """
    outbox_dir = workspace / ".agentos" / "outbox"
    if not outbox_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for path in sorted(outbox_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and "to" in data and "content" in data:
                results.append(data)
            path.unlink()
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
    return results


def write_comms_prompt_addition() -> str:
    """Return the system prompt addition for Tier 2 workspace communication."""
    return (
        "\n\n## Team Communication\n"
        "You are part of a collaborative workspace with other agents and a "
        "human manager.\n"
        "- **Before starting**, read `.agentos/board.md` for team context, "
        "announcements, and alerts.\n"
        "- **Check `.agentos/inbox/`** for direct messages from teammates.\n"
        "- **To send a message**, write a JSON file to `.agentos/outbox/` with "
        'format: `{"to": "agent_name or human", "content": "your message", '
        '"speech_act": "inform|request|propose"}`\n'
        "- **After major steps**, re-read the board and inbox for updates.\n"
    )


def cleanup_comms_files(workspace: Path) -> None:
    """Remove communication files from workspace after task completion."""
    comms_dir = workspace / ".agentos"
    if not comms_dir.exists():
        return
    for subdir in ("inbox", "outbox"):
        d = comms_dir / subdir
        if d.exists():
            for f in d.iterdir():
                f.unlink(missing_ok=True)


def extract_manifest_from_text(raw_output: str) -> dict[str, Any] | None:
    """Attempt to extract manifest-like data from agent's natural language output.

    When an agent fails to produce manifest.json, this function tries to salvage
    useful information from the raw text output. Returns a dict with
    "extraction_mode": "inferred" flag, or None if nothing useful found.
    """
    if not raw_output or not raw_output.strip():
        return None

    lines = raw_output.strip().splitlines()

    # Extract summary: first non-empty paragraph (up to 3 sentences)
    summary_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if summary_lines:
                break
            continue
        summary_lines.append(stripped)
        if len(summary_lines) >= 3:
            break
    summary = " ".join(summary_lines) if summary_lines else None

    if not summary:
        return None

    # Extract findings: bullet points or numbered lists
    findings = []
    bullet_pattern = re.compile(r"^\s*[-*\u2022]\s+(.+)")
    numbered_pattern = re.compile(r"^\s*\d+[.)]\s+(.+)")
    for line in lines:
        match = bullet_pattern.match(line) or numbered_pattern.match(line)
        if match:
            finding_text = match.group(1).strip()
            if finding_text and len(finding_text) > 10:
                findings.append({
                    "finding": finding_text,
                    "confidence": "low",
                    "sources": [],
                })

    # Extract file references: paths that look like file paths
    file_pattern = re.compile(r"(?:^|\s)([./][\w/.-]+\.\w+)")
    files_produced = list(set(file_pattern.findall(raw_output)))

    return {
        "summary": summary,
        "findings": findings[:10],  # Cap at 10
        "open_questions": [],
        "files_produced": files_produced[:20],  # Cap at 20
        "extraction_mode": "inferred",
    }
