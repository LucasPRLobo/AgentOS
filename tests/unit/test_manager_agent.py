"""Unit tests for manager_agent — team orchestration logic."""

from __future__ import annotations

import json

import pytest

from agentos.adapters.manager_agent import (
    MemberAssignment,
    ManagerPlan,
    build_manager_system_prompt,
    build_planning_task,
    build_review_task,
    parse_assignment_plan,
    parse_reassignments,
    write_member_results,
)


class TestBuildManagerSystemPrompt:
    """Tests for system prompt construction."""

    def test_includes_team_name(self):
        prompt = build_manager_system_prompt(
            team_name="research",
            team_description="Research team",
            member_roles={"analyst": "Does analysis"},
            human_input_enabled=False,
        )
        assert "research" in prompt
        assert "Research team" in prompt

    def test_includes_member_roles(self):
        prompt = build_manager_system_prompt(
            team_name="t",
            team_description="",
            member_roles={"alice": "Data analyst", "bob": "Writer"},
            human_input_enabled=False,
        )
        assert "alice" in prompt
        assert "Data analyst" in prompt
        assert "bob" in prompt
        assert "Writer" in prompt

    def test_human_input_section(self):
        prompt_with = build_manager_system_prompt(
            team_name="t", team_description="", member_roles={},
            human_input_enabled=True,
        )
        prompt_without = build_manager_system_prompt(
            team_name="t", team_description="", member_roles={},
            human_input_enabled=False,
        )
        assert "Human Oversight" in prompt_with
        assert "Human Oversight" not in prompt_without

    def test_includes_assignment_format(self):
        prompt = build_manager_system_prompt(
            team_name="t", team_description="", member_roles={},
            human_input_enabled=False,
        )
        assert "Assignment Format" in prompt
        assert "assignments" in prompt

    def test_includes_review_format(self):
        prompt = build_manager_system_prompt(
            team_name="t", team_description="", member_roles={},
            human_input_enabled=False,
        )
        assert "Review Format" in prompt
        assert "manifest.json" in prompt


class TestBuildPlanningTask:
    """Tests for planning prompt construction."""

    def test_includes_task_description(self):
        prompt = build_planning_task("Analyze NVDA", [])
        assert "Analyze NVDA" in prompt

    def test_includes_predecessor_context(self):
        prompt = build_planning_task("task", ["[prev] Did some research"])
        assert "predecessor" in prompt.lower()
        assert "Did some research" in prompt

    def test_no_predecessors(self):
        prompt = build_planning_task("task", [])
        assert "Predecessor" not in prompt


class TestBuildReviewTask:
    """Tests for review prompt construction."""

    def test_includes_member_results(self):
        results = {
            "analyst": {"summary": "Market is growing", "findings": []},
            "writer": {"summary": "Report drafted", "findings": []},
        }
        prompt = build_review_task("task", results)
        assert "analyst" in prompt
        assert "Market is growing" in prompt
        assert "writer" in prompt
        assert "Report drafted" in prompt

    def test_includes_findings(self):
        results = {
            "a": {
                "summary": "Done",
                "findings": [
                    {"finding": "Revenue up 30%", "confidence": "high"},
                ],
            },
        }
        prompt = build_review_task("task", results)
        assert "Revenue up 30%" in prompt
        assert "high" in prompt


class TestParseAssignmentPlan:
    """Tests for parsing manager's assignment output."""

    def test_parse_json_block(self):
        text = """Here's my plan:
```json
{
  "reasoning": "Need market and competitor analysis",
  "assignments": [
    {"member": "analyst", "instruction": "Analyze market", "priority": 2},
    {"member": "writer", "instruction": "Draft intro", "priority": 1}
  ]
}
```
"""
        plan = parse_assignment_plan(text)
        assert plan.reasoning == "Need market and competitor analysis"
        assert len(plan.assignments) == 2
        # Sorted by priority descending
        assert plan.assignments[0].member == "analyst"
        assert plan.assignments[0].priority == 2
        assert plan.assignments[1].member == "writer"

    def test_parse_plain_json(self):
        data = {
            "reasoning": "Simple",
            "assignments": [
                {"member": "bob", "instruction": "Do it"},
            ],
        }
        plan = parse_assignment_plan(json.dumps(data))
        assert len(plan.assignments) == 1
        assert plan.assignments[0].member == "bob"

    def test_parse_invalid_json(self):
        plan = parse_assignment_plan("not json at all")
        assert plan.assignments == []
        assert "Could not parse" in plan.reasoning

    def test_parse_human_input_request(self):
        data = {
            "reasoning": "Need client input",
            "assignments": [],
            "needs_human_input": True,
            "human_question": "Which market to focus on?",
        }
        plan = parse_assignment_plan(json.dumps(data))
        assert plan.needs_human_input is True
        assert plan.human_question == "Which market to focus on?"

    def test_parse_missing_fields(self):
        """Assignments without required fields are skipped."""
        data = {
            "assignments": [
                {"member": "a"},  # missing instruction
                {"instruction": "do it"},  # missing member
                {"member": "b", "instruction": "valid"},
            ],
        }
        plan = parse_assignment_plan(json.dumps(data))
        assert len(plan.assignments) == 1
        assert plan.assignments[0].member == "b"


class TestParseReassignments:
    """Tests for parsing reassignment requests from review manifest."""

    def test_parse_reassignments(self):
        manifest = {
            "summary": "Needs revision",
            "reassignments": [
                {"member": "analyst", "instruction": "Redo the numbers", "priority": 1},
            ],
        }
        reassignments = parse_reassignments(manifest)
        assert len(reassignments) == 1
        assert reassignments[0].member == "analyst"

    def test_no_reassignments(self):
        manifest = {"summary": "All good"}
        assert parse_reassignments(manifest) == []

    def test_empty_reassignments(self):
        manifest = {"summary": "Done", "reassignments": []}
        assert parse_reassignments(manifest) == []


class TestWriteMemberResults:
    """Tests for writing member results to workspace."""

    def test_write_results(self, tmp_path):
        results = {
            "analyst": {"summary": "Analysis done", "findings": []},
            "writer": {"summary": "Report written", "findings": []},
        }
        write_member_results(tmp_path, results)
        results_dir = tmp_path / ".team_results"
        assert results_dir.exists()
        assert (results_dir / "analyst.json").exists()
        assert (results_dir / "writer.json").exists()

        data = json.loads((results_dir / "analyst.json").read_text())
        assert data["summary"] == "Analysis done"
