"""Cost tracker — workspace-level cost tracking with per-agent/task breakdown.

Implements budget hierarchy (workspace → task → assistant),
cost-of-pass metrics, and model routing suggestions.
"""

from __future__ import annotations

from agentos.schemas.budget import BudgetDelta, BudgetSpec, BudgetUsage


# Default reserve percentage for dynamic tasks/replanning.
_DEFAULT_RESERVE_PCT = 0.30


class CacheUsage:
    """Cache-aware token breakdown for an agent/task."""

    def __init__(self) -> None:
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_read_tokens: int = 0
        self.cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens served from cache."""
        total_input = self.input_tokens + self.cache_read_tokens
        if total_input == 0:
            return 0.0
        return self.cache_read_tokens / total_input

    @property
    def effective_savings_pct(self) -> float:
        """Estimated cost savings from caching (cache reads cost ~10% of regular input)."""
        if self.cache_read_tokens == 0:
            return 0.0
        # Cache reads cost ~10% of full input tokens
        full_cost_tokens = self.input_tokens + self.cache_read_tokens
        actual_cost_tokens = self.input_tokens + (self.cache_read_tokens * 0.1)
        if full_cost_tokens == 0:
            return 0.0
        return 1.0 - (actual_cost_tokens / full_cost_tokens)


class CostTracker:
    """Tracks workspace costs and provides optimization insights.

    Includes cache-aware token tracking to help the coordinator decide
    whether to reuse agents (cache warm) or spawn fresh.
    """

    def __init__(self, budget: BudgetSpec) -> None:
        self._budget = budget
        self._total = BudgetUsage()
        self._per_agent: dict[str, BudgetUsage] = {}
        self._per_task: dict[str, BudgetUsage] = {}
        self._task_budgets: dict[str, BudgetSpec] = {}
        self._task_attempts: dict[str, int] = {}
        self._task_successes: dict[str, int] = {}
        # Cache-aware tracking
        self._cache_per_agent: dict[str, CacheUsage] = {}
        self._cache_total = CacheUsage()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        agent_id: str,
        task_id: str,
        delta: BudgetDelta,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record a cost delta for an agent working on a task.

        When *cache_read_tokens* and *cache_write_tokens* are provided,
        cache-aware tracking is updated. This helps the coordinator decide
        whether to reuse an agent (warm cache) or spawn fresh.
        """
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

        # Cache tracking
        if cache_read_tokens or cache_write_tokens or input_tokens or output_tokens:
            agent_cache = self._cache_per_agent.setdefault(agent_id, CacheUsage())
            agent_cache.input_tokens += input_tokens
            agent_cache.output_tokens += output_tokens
            agent_cache.cache_read_tokens += cache_read_tokens
            agent_cache.cache_write_tokens += cache_write_tokens

            self._cache_total.input_tokens += input_tokens
            self._cache_total.output_tokens += output_tokens
            self._cache_total.cache_read_tokens += cache_read_tokens
            self._cache_total.cache_write_tokens += cache_write_tokens

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

    # ------------------------------------------------------------------
    # Cache awareness
    # ------------------------------------------------------------------

    def get_cache_usage(self, agent_id: str | None = None) -> CacheUsage:
        """Get cache usage for an agent, or total if no agent specified."""
        if agent_id is None:
            return self._cache_total
        return self._cache_per_agent.get(agent_id, CacheUsage())

    def should_reuse_agent(self, agent_id: str) -> bool:
        """Recommend reusing an agent based on cache hit rate.

        If an agent has a high cache hit rate (>30%), reusing it is
        cheaper than spawning fresh (warm cache avoids re-prefill).
        """
        cache = self._cache_per_agent.get(agent_id)
        if cache is None:
            return False
        return cache.cache_hit_rate > 0.30
