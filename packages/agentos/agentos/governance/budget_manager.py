"""Budget manager — enforce resource limits and emit budget events."""

from __future__ import annotations

from agentos.core.errors import BudgetExceededError
from agentos.core.identifiers import RunId
from agentos.runtime.event_log import EventLog
from agentos.schemas.budget import BudgetDelta, BudgetSpec, BudgetUsage
from agentos.schemas.events import BudgetExceeded, BudgetUpdated


class BudgetManager:
    """Tracks resource usage against a BudgetSpec and enforces limits.

    Before every task execution or tool call, check() must be called.
    If any limit is exceeded, a BudgetExceeded event is emitted and
    BudgetExceededError is raised.
    """

    def __init__(
        self,
        spec: BudgetSpec,
        event_log: EventLog,
        run_id: RunId,
    ) -> None:
        self._spec = spec
        self._event_log = event_log
        self._run_id = run_id
        self._usage = BudgetUsage()
        self._seq = 0

    @property
    def usage(self) -> BudgetUsage:
        return self._usage

    @property
    def spec(self) -> BudgetSpec:
        return self._spec

    def set_seq(self, seq: int) -> None:
        """Set the current sequence counter for event emission."""
        self._seq = seq

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def check(self) -> None:
        """Check if any budget limit is exceeded.

        Raises BudgetExceededError and emits BudgetExceeded event if so.
        """
        exceeded = self._usage.exceeds(self._spec)
        if exceeded is not None:
            self._event_log.append(
                BudgetExceeded(
                    run_id=self._run_id,
                    seq=self._next_seq(),
                    payload={
                        "limit": exceeded,
                        "usage": self._usage.model_dump(),
                        "spec": self._spec.model_dump(),
                    },
                )
            )
            raise BudgetExceededError(
                f"Budget limit '{exceeded}' exceeded: "
                f"{getattr(self._usage, _USAGE_FIELD_MAP[exceeded])} "
                f">= {getattr(self._spec, exceeded)}"
            )

    def apply(self, delta: BudgetDelta) -> None:
        """Apply a usage delta and emit BudgetUpdated event."""
        self._usage = BudgetUsage(
            tokens_used=self._usage.tokens_used + delta.tokens,
            tool_calls_used=self._usage.tool_calls_used + delta.tool_calls,
            time_elapsed_seconds=self._usage.time_elapsed_seconds + delta.time_seconds,
            current_recursion_depth=self._usage.current_recursion_depth
            + delta.recursion_depth_change,
            current_parallel=self._usage.current_parallel + delta.parallel_change,
        )
        self._event_log.append(
            BudgetUpdated(
                run_id=self._run_id,
                seq=self._next_seq(),
                payload={
                    "delta": delta.model_dump(),
                    "usage": self._usage.model_dump(),
                },
            )
        )

    def record_tool_call(self) -> None:
        """Record a single tool call against the budget."""
        self.apply(BudgetDelta(tool_calls=1))

    def record_tokens(self, tokens: int) -> None:
        """Record token usage against the budget."""
        self.apply(BudgetDelta(tokens=tokens))


# Maps budget spec field names to usage field names
_USAGE_FIELD_MAP: dict[str, str] = {
    "max_tokens": "tokens_used",
    "max_tool_calls": "tool_calls_used",
    "max_time_seconds": "time_elapsed_seconds",
    "max_recursion_depth": "current_recursion_depth",
    "max_parallel": "current_parallel",
}
