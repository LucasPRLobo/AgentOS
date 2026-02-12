"""Budget specification and tracking schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetSpec(BaseModel):
    """Hard limits on resource consumption for a run."""

    max_tokens: int = Field(gt=0, description="Maximum tokens allowed")
    max_tool_calls: int = Field(gt=0, description="Maximum tool invocations allowed")
    max_time_seconds: float = Field(gt=0, description="Maximum wall-clock time in seconds")
    max_recursion_depth: int = Field(gt=0, description="Maximum recursion depth")
    max_parallel: int = Field(gt=0, default=1, description="Maximum parallel tasks")


class BudgetUsage(BaseModel):
    """Current consumption counters for a run."""

    tokens_used: int = Field(ge=0, default=0)
    tool_calls_used: int = Field(ge=0, default=0)
    time_elapsed_seconds: float = Field(ge=0, default=0.0)
    current_recursion_depth: int = Field(ge=0, default=0)
    current_parallel: int = Field(ge=0, default=0)

    def exceeds(self, spec: BudgetSpec) -> str | None:
        """Return the name of the first exceeded limit, or None."""
        if self.tokens_used >= spec.max_tokens:
            return "max_tokens"
        if self.tool_calls_used >= spec.max_tool_calls:
            return "max_tool_calls"
        if self.time_elapsed_seconds >= spec.max_time_seconds:
            return "max_time_seconds"
        if self.current_recursion_depth >= spec.max_recursion_depth:
            return "max_recursion_depth"
        if self.current_parallel > spec.max_parallel:
            return "max_parallel"
        return None


class BudgetDelta(BaseModel):
    """Incremental usage update."""

    tokens: int = Field(ge=0, default=0)
    tool_calls: int = Field(ge=0, default=0)
    time_seconds: float = Field(ge=0, default=0.0)
    recursion_depth_change: int = Field(default=0)
    parallel_change: int = Field(default=0)
