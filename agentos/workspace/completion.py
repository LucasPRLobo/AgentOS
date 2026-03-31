"""Completion detection — layered system for determining when work is done.

Layer 1: Hard limits (budget, max tasks, loop guards)
Layer 2: Goal satisfaction (acceptance criteria + all tasks done)
Layer 3: Human judgment (coordinator surfaces recommendation)
Layer 4: Scope management (flags creep)
"""

from __future__ import annotations

from agentos.schemas.budget import BudgetSpec, BudgetUsage
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.schemas import (
    BacklogTaskStatus,
    CompletionResult,
    WorkspaceConfig,
)


class CompletionDetector:
    """Layered completion detection for workspaces."""

    # Diminishing returns: if N+ consecutive completions produce minimal output
    _DIMINISHING_THRESHOLD_CHARS = 200  # Minimum chars per completion to count as progress
    _DIMINISHING_CONSECUTIVE = 3        # N consecutive low-output completions = stall

    def __init__(
        self,
        config: WorkspaceConfig,
        backlog: BacklogManager,
        budget_usage: BudgetUsage | None = None,
        max_tasks: int = 100,
    ) -> None:
        self._config = config
        self._backlog = backlog
        self._budget_usage = budget_usage or BudgetUsage()
        self._max_tasks = max_tasks
        self._initial_task_count: int | None = None
        # Diminishing returns tracking
        self._recent_outputs: list[int] = []  # char counts of recent task outputs

    def set_initial_task_count(self, count: int) -> None:
        self._initial_task_count = count

    def update_budget_usage(self, usage: BudgetUsage) -> None:
        self._budget_usage = usage

    def record_task_output(self, output_chars: int) -> None:
        """Record the size of a task's output for diminishing returns detection."""
        self._recent_outputs.append(output_chars)
        if len(self._recent_outputs) > self._DIMINISHING_CONSECUTIVE * 2:
            self._recent_outputs = self._recent_outputs[-self._DIMINISHING_CONSECUTIVE * 2:]

    def check(self) -> CompletionResult:
        """Run all layers in order. Return first triggered result."""
        # Layer 1: Hard limits
        result = self._check_hard_limits()
        if result.complete or result.reason:
            return result

        # Layer 1b: Diminishing returns (safety net)
        result = self._check_diminishing_returns()
        if result.reason:
            return result

        # Layer 4: Scope management (check before goal satisfaction — scope creep overrides)
        scope = self._check_scope()
        if scope.reason:
            return scope

        # Layer 2: Goal satisfaction
        result = self._check_goal_satisfaction()
        if result.complete or result.reason:
            return result

        # Layer 3: Not complete yet — surface status for human
        return CompletionResult(
            complete=False,
            reason="in_progress",
            layer=3,
            recommendation="Work in progress. Check board for status.",
        )

    def _check_hard_limits(self) -> CompletionResult:
        budget = self._config.budget

        # Cost limit
        if budget.max_cost_usd and self._budget_usage.cost_usd >= budget.max_cost_usd:
            return CompletionResult(
                complete=True, reason="budget_exhausted", layer=1,
                details={"dimension": "cost_usd", "used": self._budget_usage.cost_usd,
                          "limit": budget.max_cost_usd},
                recommendation="Budget exhausted. Review partial output.",
            )

        # Token limit
        if budget.max_tokens and self._budget_usage.tokens_used >= budget.max_tokens:
            return CompletionResult(
                complete=True, reason="budget_exhausted", layer=1,
                details={"dimension": "tokens", "used": self._budget_usage.tokens_used,
                          "limit": budget.max_tokens},
                recommendation="Token budget exhausted. Review partial output.",
            )

        # Time limit
        if budget.max_time_seconds and self._budget_usage.time_elapsed_seconds >= budget.max_time_seconds:
            return CompletionResult(
                complete=True, reason="budget_exhausted", layer=1,
                details={"dimension": "time", "used": self._budget_usage.time_elapsed_seconds,
                          "limit": budget.max_time_seconds},
                recommendation="Time budget exhausted.",
            )

        # Max task count
        total_tasks = len(self._backlog.get_all_tasks())
        if total_tasks > self._max_tasks:
            return CompletionResult(
                complete=False, reason="max_tasks_exceeded", layer=1,
                details={"total_tasks": total_tasks, "limit": self._max_tasks},
                recommendation=f"Task count ({total_tasks}) exceeds limit ({self._max_tasks}). "
                               f"Review scope with human.",
            )

        return CompletionResult()

    def _check_goal_satisfaction(self) -> CompletionResult:
        tasks = self._backlog.get_all_tasks()
        done = [t for t in tasks if t.status == BacklogTaskStatus.DONE]
        active = [t for t in tasks if t.status not in
                  (BacklogTaskStatus.DONE, BacklogTaskStatus.CANCELLED)]

        if not tasks:
            return CompletionResult(complete=False, reason="no_tasks", layer=2)

        # All tasks done?
        if active:
            return CompletionResult(
                complete=False, reason="tasks_remaining", layer=2,
                details={"done": len(done), "remaining": len(active)},
            )

        # All tasks done — check acceptance criteria
        criteria = self._config.acceptance_criteria
        if not criteria:
            return CompletionResult(
                complete=True, reason="all_tasks_done", layer=2,
                recommendation="All tasks complete. No acceptance criteria defined — "
                               "human review recommended.",
            )

        return CompletionResult(
            complete=True, reason="goal_satisfied", layer=2,
            details={"tasks_done": len(done), "criteria": criteria},
            recommendation="All tasks complete. Acceptance criteria should be evaluated "
                           "by coordinator or human.",
        )

    def _check_diminishing_returns(self) -> CompletionResult:
        """Detect when agents are producing minimal output per completion."""
        if len(self._recent_outputs) < self._DIMINISHING_CONSECUTIVE:
            return CompletionResult()

        recent = self._recent_outputs[-self._DIMINISHING_CONSECUTIVE:]
        if all(c < self._DIMINISHING_THRESHOLD_CHARS for c in recent):
            return CompletionResult(
                complete=False,
                reason="diminishing_returns",
                layer=1,
                details={
                    "consecutive_low_output": len(recent),
                    "threshold_chars": self._DIMINISHING_THRESHOLD_CHARS,
                    "recent_output_chars": recent,
                },
                recommendation=(
                    f"Last {len(recent)} task completions produced minimal output "
                    f"(<{self._DIMINISHING_THRESHOLD_CHARS} chars each). "
                    f"Agents may be spinning without progress. Consider human review."
                ),
            )
        return CompletionResult()

    def _check_scope(self) -> CompletionResult:
        if self._initial_task_count is None:
            return CompletionResult()

        current = len(self._backlog.get_all_tasks())
        growth = current - self._initial_task_count
        if growth > self._initial_task_count:  # More than doubled
            return CompletionResult(
                complete=False, reason="scope_creep", layer=4,
                details={"initial_tasks": self._initial_task_count,
                          "current_tasks": current, "growth": growth},
                recommendation=f"Task count grew from {self._initial_task_count} to {current}. "
                               f"Review scope with human.",
            )
        return CompletionResult()
