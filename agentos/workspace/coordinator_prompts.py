"""Prompt templates for the workspace coordinator agent."""

from __future__ import annotations

from agentos.workspace.schemas import WorkspaceConfig, WorkspaceContextSummary


def build_decomposition_prompt(
    config: WorkspaceConfig,
    document_summaries: list[str] | None = None,
) -> str:
    team_lines = []
    for p in config.team:
        roles = ", ".join(str(r) for r in p.roles)
        team_lines.append(f"- {p.name} ({p.type}, roles: {roles}): {p.specialization}")

    docs = "\n".join(f"- {d}" for d in (document_summaries or config.documents)) or "None"
    criteria = "\n".join(f"- {c}" for c in config.acceptance_criteria) or "None specified"

    return f"""You are a project coordinator. Your job is to decompose a goal into concrete, actionable tasks for your team. You do NOT execute tasks yourself.

## Goal
{config.goal}

## Description
{config.description or 'No additional description.'}

## Acceptance Criteria
{criteria}

## Team
{chr(10).join(team_lines) or 'No team members yet.'}

## Documents Available
{docs}

## Instructions
Decompose this goal into tasks. For each task provide a JSON object:
- "title": short task name
- "description": what to do (specific, non-overlapping with other tasks)
- "suggested_for": team member name best suited (or null)
- "required_role": role type needed (or null)
- "depends_on_titles": list of other task titles this depends on (or [])
- "acceptance_criteria": list of strings
- "estimated_minutes": integer estimate
- "priority": "low" | "normal" | "high" | "critical"
- "model_tier": "haiku" | "sonnet" | "opus" (cost recommendation)

Also provide:
- "plan_summary": 2-3 sentence overview of the approach
- "parallel_groups": which tasks can run simultaneously

Respond with a JSON object: {{"tasks": [...], "plan_summary": "...", "parallel_groups": [["title1", "title2"], ...]}}

Rules:
- Tasks must be specific and non-overlapping
- Flag tasks estimated at >35 minutes for decomposition
- Each task needs clear acceptance criteria
- Use cheaper models (haiku/sonnet) for routine work, opus only for complex reasoning"""


def build_replan_prompt(
    workspace_summary: WorkspaceContextSummary,
    completed_tasks: list[str],
    failed_tasks: list[str],
    board_compact: str,
) -> str:
    return f"""You are the project coordinator. Progress has stalled — review the situation and replan.

## Current State
{board_compact}

## Workspace Summary
Goal: {workspace_summary.goal}
Status: {workspace_summary.current_status}
Tasks completed: {workspace_summary.tasks_completed}
Tasks remaining: {workspace_summary.tasks_remaining}
Budget consumed: {workspace_summary.budget_consumed_pct:.0%}

## Facts
{chr(10).join('- ' + f for f in workspace_summary.facts) or 'None yet.'}

## Educated Guesses
{chr(10).join('- ' + g for g in workspace_summary.educated_guesses) or 'None.'}

## Current Plan
{chr(10).join('- ' + s for s in workspace_summary.current_plan) or 'No active plan.'}

## Recently Completed
{chr(10).join('- ' + t for t in completed_tasks) or 'None.'}

## Failed Tasks
{chr(10).join('- ' + t for t in failed_tasks) or 'None.'}

## Instructions
Assess the situation and produce a revised plan. Respond with JSON:
{{
  "assessment": "What's going well, what's stuck, why",
  "new_tasks": [... same format as decomposition ...],
  "cancel_tasks": ["task_id", ...],
  "reassign_tasks": [{{"task_id": "...", "new_assignee": "..."}}],
  "updated_plan": ["step 1", "step 2", ...],
  "team_changes": [... if needed: {{"action": "add"|"remove", "name": "...", "specialization": "...", "reason": "..."}} ...]
}}"""


def build_completion_assessment_prompt(
    config: WorkspaceConfig,
    workspace_summary: WorkspaceContextSummary,
    artifacts: list[str],
    board_compact: str,
) -> str:
    criteria = "\n".join(f"- {c}" for c in config.acceptance_criteria) or "None specified"
    artifact_list = "\n".join(f"- {a}" for a in artifacts) or "None"

    return f"""You are the project coordinator. All planned tasks are done. Assess whether the goal is met.

## Goal
{config.goal}

## Acceptance Criteria
{criteria}

## Produced Artifacts
{artifact_list}

## Board State
{board_compact}

## Summary
{workspace_summary.current_status}

## Instructions
Evaluate each acceptance criterion. Respond with JSON:
{{
  "criteria_status": [{{"criterion": "...", "met": true/false, "evidence": "..."}}],
  "overall_complete": true/false,
  "recommendation": "complete" | "continue with X" | "needs human review",
  "summary": "2-3 sentence assessment"
}}"""


def build_failure_recovery_prompt(
    task_title: str,
    error: str,
    attempt_number: int,
    available_agents: list[str],
) -> str:
    agents = ", ".join(available_agents) or "None available"
    return f"""A task has failed. Decide the next step.

## Failed Task
{task_title}

## Error
{error}

## Attempt Number
{attempt_number} (1=first failure, 2=already retried once, etc.)

## Available Agents
{agents}

## Escalation Ladder
1. Retry (same agent, same task) — for transient failures
2. Reassign (same task, different agent) — agent-specific problem
3. Replan (same goal, different approach) — approach was wrong
4. Decompose (break into smaller pieces) — task too large/complex
5. Escalate to human — coordinator can't resolve

## Instructions
Choose the appropriate step. Respond with JSON:
{{
  "action": "retry" | "reassign" | "replan" | "decompose" | "escalate",
  "reason": "why this action",
  "reassign_to": "agent name" (if reassign),
  "sub_tasks": [...] (if decompose),
  "message_to_human": "..." (if escalate)
}}"""
