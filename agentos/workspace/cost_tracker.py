"""Cost tracker — workspace-level cost tracking with per-agent/task breakdown.

Implements budget hierarchy (workspace → task → assistant),
cost-of-pass metrics, and model routing suggestions.
"""

from __future__ import annotations

from agentos.schemas.budget import BudgetDelta, BudgetSpec, BudgetUsage


# Default reserve percentage for dynamic tasks/replanning.
_DEFAULT_RESERVE_PCT = 0.30


class CostTracker:
    """Tracks workspace costs and provides optimization insights."""

    def __init__(self, budget: BudgetSpec) -> None:
        self._budget = budget
        self._total = BudgetUsage()
        self._per_agent: dict[str, BudgetUsage] = {}
        self._per_task: dict[str, BudgetUsage] = {}
        self._task_budgets: dict[str, BudgetSpec] = {}
        self._task_attempts: dict[str, int] = {}
        self._task_successes: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, agent_id: str, task_id: str, delta: BudgetDelta) -> None:
        """Record a cost delta for an agent working on a task."""
        self._total.tokens_used += delta.tokens
        self._total.api_calls_made += delta.api_calls
        self._total.time_elapsed_seconds += delta.time_seconds
        self._total.cost_usd += delta.cost_usd

        agent_usage = self._per_agent.setdefault(agent_id, BudgetUsage())
        agent_usage.tokens_used += delta.tokens
        agent_usage.api_calls_made += delta.api_calls
        agent_usage.time_elapsed_seconds += delta.time_seconds
        agent_usage.cost_usd += delta.cost_usd

        task_usage = self._per_task.setdefault(task_id, BudgetUsage())
        task_usage.tokens_used += delta.tokens
        task_usage.api_calls_made += delta.api_calls
        task_usage.time_elapsed_seconds += delta.time_seconds
        task_usage.cost_usd += delta.cost_usd

    def record_task_attempt(self, task_id: str, success: bool) -> None:
        """Record a task attempt for cost-of-pass calculation."""
        self._task_attempts[task_id] = self._task_attempts.get(task_id, 0) + 1
        if success:
            self._task_successes[task_id] = self._task_successes.get(task_id, 0) + 1

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_total(self) -> BudgetUsage:
        return self._total

    def get_per_agent(self, agent_id: str) -> BudgetUsage:
        return self._per_agent.get(agent_id, BudgetUsage())

    def get_per_task(self, task_id: str) -> BudgetUsage:
        return self._per_task.get(task_id, BudgetUsage())

    # ------------------------------------------------------------------
    # Budget hierarchy
    # ------------------------------------------------------------------

    def allocate_for_task(self, task_id: str, budget: BudgetSpec) -> None:
        """Allocate a budget for a specific task."""
        self._task_budgets[task_id] = budget

    def get_remaining_for_task(self, task_id: str) -> BudgetSpec | None:
        """Get remaining budget for a task."""
        allocated = self._task_budgets.get(task_id)
        if allocated is None:
            return None
        used = self._per_task.get(task_id, BudgetUsage())
        return BudgetSpec(
            max_tokens=(allocated.max_tokens - used.tokens_used) if allocated.max_tokens else None,
            max_cost_usd=(allocated.max_cost_usd - used.cost_usd) if allocated.max_cost_usd else None,
            max_time_seconds=(allocated.max_time_seconds - used.time_elapsed_seconds) if allocated.max_time_seconds else None,
        )

    def get_reserve(self) -> float:
        """Get unallocated budget in USD (the reserve for dynamic work)."""
        if not self._budget.max_cost_usd:
            return float("inf")
        allocated = sum(
            (b.max_cost_usd or 0) for b in self._task_budgets.values()
        )
        return max(0, self._budget.max_cost_usd - allocated)

    def get_budget_consumed_pct(self) -> float:
        """Percentage of workspace budget consumed."""
        if self._budget.max_cost_usd and self._budget.max_cost_usd > 0:
            return min(1.0, self._total.cost_usd / self._budget.max_cost_usd)
        if self._budget.max_tokens and self._budget.max_tokens > 0:
            return min(1.0, self._total.tokens_used / self._budget.max_tokens)
        return 0.0

    # ------------------------------------------------------------------
    # Cost-of-pass
    # ------------------------------------------------------------------

    def cost_of_pass(self, task_id: str) -> float | None:
        """Expected cost per correct result: cost / success_rate."""
        attempts = self._task_attempts.get(task_id, 0)
        successes = self._task_successes.get(task_id, 0)
        if attempts == 0:
            return None
        usage = self._per_task.get(task_id)
        if usage is None:
            return None
        cost_per_attempt = usage.cost_usd / attempts
        success_rate = successes / attempts if attempts else 0
        if success_rate <= 0:
            return None
        return cost_per_attempt / success_rate

    # ------------------------------------------------------------------
    # Model routing
    # ------------------------------------------------------------------

    @staticmethod
    def suggest_model_tier(estimated_complexity: str) -> str:
        """Suggest a model tier based on task complexity description."""
        complexity = estimated_complexity.lower()
        if any(w in complexity for w in ("simple", "format", "extract", "copy", "list", "routine")):
            return "haiku"
        if any(w in complexity for w in ("complex", "synthesize", "strategy", "judgment", "creative")):
            return "opus"
        return "sonnet"
