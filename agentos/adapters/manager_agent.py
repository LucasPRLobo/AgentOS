"""Manager Agent — team orchestration logic for LLM-powered supervisors.

The manager is a Claude Code (or other Tier 2) instance that coordinates a
team of member agents.  This module handles prompt construction, parsing
the manager's structured assignment output, and round management.

Orchestration flow:
  1. Manager CC instance receives task + team roster → produces assignment plan
  2. Adapter dispatches each assignment to the appropriate member adapter
  3. Member results are formatted and fed back to the manager
  4. Manager reviews all results → produces consolidated TaskOutput

The manager never calls the Anthropic API directly — it's a real Claude Code
instance just like the other agents, but with a richer prompt and visibility
into member work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Maximum rounds of manager ↔ member interaction before forcing completion.
MAX_SUPERVISION_ROUNDS = 5


@dataclass
class MemberAssignment:
    """A work assignment from the manager to a team member."""

    member: str
    instruction: str
    priority: int = 0  # higher = do first


@dataclass
class ManagerPlan:
    """Parsed output from the manager's planning round."""

    assignments: list[MemberAssignment] = field(default_factory=list)
    reasoning: str = ""
    needs_human_input: bool = False
    human_question: str = ""


def build_manager_system_prompt(
    team_name: str,
    team_description: str,
    member_roles: dict[str, str],
    human_input_enabled: bool,
) -> str:
    """Build the role/system section of the manager's prompt.

    This is injected as the ``role`` parameter when the manager's adapter
    runs, giving it full context about its team.
    """
    parts = [
        f"You are the manager of the **{team_name}** team.",
        f"\n## Team Purpose\n{team_description}" if team_description else "",
        "\n## Your Team Members",
    ]

    for member_name, role in member_roles.items():
        role_desc = role if role else "(no role description)"
        parts.append(f"- **{member_name}**: {role_desc}")

    parts.append(
        "\n## Your Responsibilities\n"
        "1. Analyze the task and break it into sub-tasks for your team members.\n"
        "2. Assign work to the most appropriate member(s) based on their roles.\n"
        "3. Review member outputs for quality — re-assign with feedback if needed.\n"
        "4. Produce a consolidated final output that synthesizes all member work."
    )

    if human_input_enabled:
        parts.append(
            "\n## Human Oversight\n"
            "You can request human input when you need clarification or a decision. "
            "Set `needs_human_input: true` in your assignments JSON and include "
            "the question in `human_question`."
        )

    parts.append(
        "\n## CRITICAL: You are a MANAGER, not a worker\n"
        "**DO NOT** perform any research, analysis, web searches, or coding yourself.\n"
        "**DO NOT** use tools like WebSearch, Bash, or WebFetch.\n"
        "Your ONLY job is to assign work to your team members listed above.\n"
        "Your team members will do the actual work. You plan, delegate, and review.\n"
        "\n## Assignment Format\n"
        "When you receive a task, create a file called `assignment_plan.json` "
        "with your delegation plan:\n"
        "```json\n"
        "{\n"
        '  "reasoning": "Brief explanation of your delegation strategy",\n'
        '  "assignments": [\n'
        '    {"member": "member_name", "instruction": "Detailed instructions for them", "priority": 1}\n'
        "  ],\n"
        '  "needs_human_input": false,\n'
        '  "human_question": ""\n'
        "}\n"
        "```\n"
        "Assign to members by their exact name from your team roster above.\n"
        "Higher priority = execute first. You can assign to multiple members.\n"
        "Give each member clear, detailed instructions so they know exactly what to do."
    )

    parts.append(
        "\n## Review Format\n"
        "After seeing member results, create `manifest.json` with your consolidated output:\n"
        "```json\n"
        "{\n"
        '  "summary": "Consolidated summary of all team work",\n'
        '  "findings": [{"finding": "...", "confidence": "high|medium|low", "sources": []}],\n'
        '  "open_questions": ["any unresolved items"],\n'
        '  "files_produced": ["list of files"],\n'
        '  "reassignments": [\n'
        '    {"member": "member_name", "instruction": "Redo X because Y", "priority": 1}\n'
        "  ]\n"
        "}\n"
        "```\n"
        "If quality is acceptable, omit `reassignments` (or set it to `[]`).\n"
        "If you need members to redo work, include `reassignments` and they "
        "will be executed before your output is finalized."
    )

    return "\n".join(p for p in parts if p)


def build_planning_task(
    task_description: str,
    predecessor_summaries: list[str],
    workspace_files: list[str] | None = None,
) -> str:
    """Build the task prompt for the manager's planning round."""
    parts = [task_description]

    if predecessor_summaries:
        parts.append("\n## Context from predecessor tasks")
        for summary in predecessor_summaries:
            parts.append(f"- {summary}")

    if workspace_files:
        parts.append("\n## Available files in workspace")
        parts.append("These files were produced by predecessor tasks and are "
                      "available for you and your team members to read:")
        for f in workspace_files[:50]:  # cap at 50 to avoid prompt bloat
            parts.append(f"  - {f}")

    parts.append(
        "\n## Instructions\n"
        "DO NOT do the work yourself. DO NOT search the web or run commands.\n"
        "Create the file `assignment_plan.json` with your delegation plan.\n"
        "Decide which team members should handle which parts of the work.\n"
        "Give each member specific, detailed instructions including the "
        "full file paths they need to read.\n"
        "Then create `manifest.json` summarizing your plan."
    )

    return "\n".join(parts)


def build_review_task(
    original_task: str,
    member_results: dict[str, dict[str, Any]],
) -> str:
    """Build the task prompt for the manager's review round.

    ``member_results`` maps member name → their manifest/output dict.
    """
    parts = [
        f"## Original Task\n{original_task}",
        "\n## Member Results",
    ]

    for member_name, result in member_results.items():
        summary = result.get("summary", "(no summary)")
        findings = result.get("findings", [])
        parts.append(f"\n### {member_name}")
        parts.append(f"Summary: {summary}")
        if findings:
            parts.append("Findings:")
            for f in findings:
                if isinstance(f, dict):
                    conf = f.get("confidence", "?")
                    parts.append(f"  - [{conf}] {f.get('finding', '')}")

    parts.append(
        "\n## Instructions\n"
        "Review the member results above. Then create `manifest.json` with your "
        "consolidated output. If any member's work needs revision, include "
        "`reassignments` in the manifest."
    )

    return "\n".join(parts)


def parse_assignment_plan(text: str) -> ManagerPlan:
    """Parse the manager's assignment plan from its text output.

    Looks for a JSON block in ```json fences, or tries to parse the whole
    text as JSON.  Returns a ManagerPlan with assignments extracted.
    """
    json_str = _extract_json_block(text)
    if json_str is None:
        # Try the whole text as JSON
        json_str = text.strip()

    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        # Manager didn't produce valid JSON — return empty plan
        return ManagerPlan(reasoning=f"Could not parse plan from manager output: {text[:200]}")

    assignments = []
    for a in data.get("assignments", []):
        if isinstance(a, dict) and "member" in a and "instruction" in a:
            assignments.append(MemberAssignment(
                member=a["member"],
                instruction=a["instruction"],
                priority=a.get("priority", 0),
            ))

    # Sort by priority descending (higher = first)
    assignments.sort(key=lambda x: -x.priority)

    return ManagerPlan(
        assignments=assignments,
        reasoning=data.get("reasoning", ""),
        needs_human_input=data.get("needs_human_input", False),
        human_question=data.get("human_question", ""),
    )


def parse_reassignments(manifest: dict[str, Any]) -> list[MemberAssignment]:
    """Extract reassignment requests from the manager's review manifest."""
    reassignments = []
    for a in manifest.get("reassignments", []):
        if isinstance(a, dict) and "member" in a and "instruction" in a:
            reassignments.append(MemberAssignment(
                member=a["member"],
                instruction=a["instruction"],
                priority=a.get("priority", 0),
            ))
    reassignments.sort(key=lambda x: -x.priority)
    return reassignments


def write_member_results(
    workspace: Path,
    member_results: dict[str, dict[str, Any]],
) -> None:
    """Write member results to workspace so the manager can see them."""
    results_dir = workspace / ".team_results"
    results_dir.mkdir(exist_ok=True)
    for member_name, result in member_results.items():
        path = results_dir / f"{member_name}.json"
        path.write_text(json.dumps(result, indent=2, default=str))


def _extract_json_block(text: str) -> str | None:
    """Extract the first ```json ... ``` block from text."""
    start = text.find("```json")
    if start == -1:
        # Try plain ``` block
        start = text.find("```\n{")
        if start == -1:
            return None
        start += 4  # skip ```\n
    else:
        start += 7  # skip ```json
        # Skip optional newline after ```json
        if start < len(text) and text[start] == "\n":
            start += 1

    end = text.find("```", start)
    if end == -1:
        return None

    return text[start:end].strip()
