"""Facilitator prompts — discussion-driven coordinator behavior.

The coordinator is a conversational partner, not a task dispatcher.
These prompts generate discussion-opening messages that invite the
human to think WITH the team, not just approve outputs.
"""

from __future__ import annotations

from agentos.workspace.schemas import WorkspaceConfig


def build_kickoff_prompt(config: WorkspaceConfig) -> str:
    """Prompt for the coordinator to open a kickoff discussion."""
    team_lines = []
    for p in config.team:
        roles = ", ".join(str(r) for r in p.roles)
        team_lines.append(f"- {p.name} ({p.type}, {roles}): {p.specialization}")

    criteria = "\n".join(f"- {c}" for c in config.acceptance_criteria) or "None specified"

    return f"""You are the workspace coordinator. A new project has been created.

## Goal
{config.goal}

## Description
{config.description or 'No additional description.'}

## Team
{chr(10).join(team_lines) or 'No team members yet.'}

## Acceptance Criteria
{criteria}

## Your Job
Open a discussion with the human lead. You need to UNDERSTAND their intent
before planning anything. Be conversational and curious, not formal.

Write an opening message that:
1. Briefly reflects back what you understand the goal to be (show you get it)
2. Asks 2-3 focused questions that would shape your approach
3. Shares your initial thinking: "Based on this, I'm considering [approach]"
4. Offers 2-3 options if there's a meaningful choice to make

Be specific, not generic. Reference the team members by name.
Ask questions that reveal priorities and constraints.

DO NOT create tasks yet. Wait for the human's input.

Respond with JSON:
{{
  "opening_message": "Your conversational message to the human",
  "questions": ["question 1", "question 2"],
  "initial_thinking": "What you're considering and why",
  "options": ["Option A: ...", "Option B: ..."]
}}"""


def build_plan_from_discussion_prompt(
    config: WorkspaceConfig,
    discussion_messages: list[dict],
) -> str:
    """Prompt to create a plan from the kickoff discussion."""
    conversation = ""
    for msg in discussion_messages:
        sender = msg.get("sender_id", "unknown")
        content = msg.get("content", "")
        conversation += f"\n{sender}: {content}\n"

    team_lines = [f"- {p.name}: {p.specialization}" for p in config.team if p.type == "agent"]

    return f"""Based on the kickoff discussion, create a task plan.

## Discussion
{conversation}

## Available Agents
{chr(10).join(team_lines)}

## Instructions
Create tasks based on what was discussed and agreed. For each task:
- Title (clear, specific)
- Description (what to do, non-overlapping with other tasks)
- Spec: what the output should look like
- Approach: how to do it
- Suggested agent (with reasoning)
- Dependencies (which tasks must complete first)
- Estimated minutes

Also write a brief message confirming the plan with the human:
"Here's the plan based on our discussion: [summary]. Does this look right?"

Respond with JSON:
{{
  "plan_summary": "2-3 sentence overview",
  "confirmation_message": "Message to human confirming the plan",
  "tasks": [
    {{
      "title": "...",
      "description": "...",
      "spec": "What the output should include",
      "approach": "How to approach this",
      "expected_output": "What success looks like",
      "suggested_for": "agent name",
      "depends_on_titles": [],
      "estimated_minutes": 10,
      "priority": "high"
    }}
  ]
}}"""


def build_check_in_prompt(
    task_title: str,
    event_summary: str,
    board_compact: str,
) -> str:
    """Prompt to decide if a check-in discussion is needed."""
    return f"""A task event has occurred. Decide if the human needs to know.

## Task: {task_title}
## What Happened: {event_summary}
## Current Board State:
{board_compact}

## Decision Criteria
Open a discussion with the human if:
- Something unexpected was found
- A direction decision is needed
- Quality or scope concern
- Task failed or is stuck
- A finding changes the project direction

Do NOT interrupt for:
- Routine progress (agent is working normally)
- Expected completion of straightforward tasks
- Minor technical details

If a discussion IS needed, write a brief, conversational message:
- Summarize what happened (2-3 sentences, not more)
- Flag what matters to the human
- Ask ONE specific question with a recommendation

Respond with JSON:
{{
  "needs_discussion": true/false,
  "message": "Your message to the human (if needed)",
  "question": "Specific question (if needed)",
  "recommendation": "What you suggest and why"
}}"""


def build_review_prompt(
    task_title: str,
    task_spec: str,
    output_summary: str,
    output_findings: list[str],
) -> str:
    """Prompt to open a review discussion after task completion."""
    findings_text = "\n".join(f"- {f}" for f in output_findings) or "No specific findings."

    return f"""A task has been completed. Review the output and discuss with the human.

## Task: {task_title}
## Original Spec: {task_spec}
## Output Summary: {output_summary}
## Findings:
{findings_text}

## Your Job
Compare the output against the original spec. Then write a review message:
1. Summarize what was accomplished (brief)
2. Note what matches the spec and what doesn't
3. Flag strengths and gaps
4. Suggest next steps with options

Be conversational: "Here's what [agent] produced. [observation].
I think we should [recommendation]. What do you think?"

Respond with JSON:
{{
  "review_message": "Conversational review for the human",
  "spec_match": "full" / "partial" / "missed",
  "gaps": ["..."],
  "strengths": ["..."],
  "options": ["Accept and move on", "Refine: ...", "Go deeper on: ..."],
  "recommendation": "Which option and why"
}}"""


def build_replan_prompt(
    current_plan: list[str],
    completed: list[str],
    issues: list[str],
    board_compact: str,
) -> str:
    """Prompt to open a replanning discussion."""
    return f"""The current plan needs adjustment. Discuss with the human.

## Current Plan
{chr(10).join(f'- {s}' for s in current_plan) or 'No active plan.'}

## Completed
{chr(10).join(f'- {s}' for s in completed) or 'Nothing yet.'}

## Issues
{chr(10).join(f'- {s}' for s in issues) or 'None.'}

## Board
{board_compact}

## Your Job
Explain what needs to change and why, then propose options.
Be honest about what went wrong or what was learned.
Give the human enough context to make a good decision.

Respond with JSON:
{{
  "replan_message": "Conversational message explaining the situation",
  "what_changed": "What triggered the need to replan",
  "options": ["Continue with adjustments: ...", "Pivot to: ...", "Pause and reassess"],
  "recommendation": "What you suggest and why"
}}"""
