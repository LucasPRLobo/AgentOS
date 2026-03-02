"""Recursive executor — implements the RLM algorithm (Algorithm 1)."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.errors import BudgetExceededError
from agentos.core.identifiers import RunId, generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.lm.provider import BaseLMProvider, LMMessage
from agentos.lm.repl import REPLEnvironment
from agentos.runtime.event_log import EventLog
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.events import (
    LMCallFinished,
    LMCallStarted,
    REPLExecFinished,
    REPLExecStarted,
    RLMIterationFinished,
    RLMIterationStarted,
    RunFinished,
    RunStarted,
)

logger = logging.getLogger(__name__)


class RLMConfig(BaseModel):
    """Configuration for the RecursiveExecutor."""

    system_prompt: str = Field(
        default=(
            "You are an RLM (Recursive Language Model) agent. "
            "You have access to a persistent Python REPL. "
            "The user's prompt is stored in variable P. "
            "You can call lm_query(text) to make sub-LM queries. "
            "Write Python code to process the prompt. "
            "When done, assign your final answer to a variable called FINAL."
        ),
        description="System prompt for the LM",
    )
    max_iterations: int = Field(
        default=100, gt=0, description="Maximum REPL iterations"
    )
    max_stdout_in_history: int = Field(
        default=500,
        ge=0,
        description="Max chars of stdout to include in history metadata",
    )
    max_recursion_depth: int = Field(
        default=1, ge=0, description="Max depth for nested lm_query calls"
    )


class _SeqCounter:
    """Mutable sequence counter shared between executor and closures."""

    __slots__ = ("value",)

    def __init__(self, start: int = 0) -> None:
        self.value = start

    def next(self) -> int:
        v = self.value
        self.value += 1
        return v


class RecursiveExecutor:
    """Executes the RLM algorithm: LM generates code, REPL executes it, repeat.

    Follows the same constructor pattern as WorkflowExecutor/DAGExecutor:
    ``__init__(event_log)`` with ``run()`` returning a ``RunId``.
    """

    def __init__(
        self,
        event_log: EventLog,
        lm_provider: BaseLMProvider,
        *,
        budget_manager: BudgetManager | None = None,
        stop_checker: StopConditionChecker | None = None,
    ) -> None:
        self._event_log = event_log
        self._lm_provider = lm_provider
        self._budget_manager = budget_manager
        self._stop_checker = stop_checker

    def run(
        self,
        prompt: str,
        *,
        run_id: RunId | None = None,
        config: RLMConfig | None = None,
        extra_vars: dict[str, Any] | None = None,
        extra_functions: dict[str, Callable] | None = None,
    ) -> tuple[RunId, str | None]:
        """Execute the RLM loop on the given prompt.

        Returns (run_id, final_result) where final_result is the string
        value of FINAL if set, or None if not reached.
        """
        cfg = config or RLMConfig()
        rid = run_id or generate_run_id()
        seq = _SeqCounter(0)

        # 1. Emit RunStarted
        self._event_log.append(
            RunStarted(
                run_id=rid,
                seq=seq.next(),
                payload={"executor": "RecursiveExecutor", "prompt_length": len(prompt)},
            )
        )

        # 2. Build lm_query closure (shares seq counter)
        lm_query = self._build_lm_query_closure(rid, cfg, seq)

        # 3. Init REPL
        initial_vars: dict[str, Any] = {"P": prompt}
        if extra_vars:
            initial_vars.update(extra_vars)
        functions: dict[str, Callable] = {"lm_query": lm_query}
        if extra_functions:
            functions.update(extra_functions)
        repl = REPLEnvironment(
            initial_vars=initial_vars,
            injected_functions=functions,
        )

        # 4. Build initial history
        history: list[LMMessage] = [
            LMMessage(role="system", content=cfg.system_prompt),
            LMMessage(
                role="user",
                content=f"Process the following prompt:\n\n{prompt}",
            ),
        ]

        outcome = "MAX_ITERATIONS"
        final_result: str | None = None

        try:
            # 5. Main loop
            for iteration in range(1, cfg.max_iterations + 1):
                # 5a. Budget check
                if self._budget_manager is not None:
                    self._budget_manager.set_seq(seq.value)
                    self._budget_manager.check()
                    seq.value = max(seq.value, self._budget_manager._seq)  # noqa: SLF001

                # 5b. Stop condition check
                if self._stop_checker is not None:
                    stop_reason = self._stop_checker.check(seq.next())
                    if stop_reason is not None:
                        outcome = "STOPPED"
                        break

                # 5c. Emit RLMIterationStarted
                self._event_log.append(
                    RLMIterationStarted(
                        run_id=rid,
                        seq=seq.next(),
                        payload={"iteration": iteration},
                    )
                )

                # 5d. LM call for code generation
                self._event_log.append(
                    LMCallStarted(
                        run_id=rid,
                        seq=seq.next(),
                        payload={
                            "call_type": "code_generation",
                            "iteration": iteration,
                            "history_length": len(history),
                        },
                    )
                )

                lm_start = time.monotonic()
                response = self._lm_provider.complete(history)
                lm_duration = time.monotonic() - lm_start
                code = response.content

                code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]

                self._event_log.append(
                    LMCallFinished(
                        run_id=rid,
                        seq=seq.next(),
                        payload={
                            "call_type": "code_generation",
                            "code_hash": code_hash,
                            "code_length": len(code),
                            "tokens_used": response.tokens_used,
                            "duration_seconds": lm_duration,
                        },
                    )
                )

                # Record tokens in budget
                if self._budget_manager is not None:
                    self._budget_manager.set_seq(seq.value)
                    self._budget_manager.record_tokens(response.tokens_used)
                    seq.value = max(seq.value, self._budget_manager._seq)  # noqa: SLF001

                # 5e. REPL execution
                self._event_log.append(
                    REPLExecStarted(
                        run_id=rid,
                        seq=seq.next(),
                        payload={"code_hash": code_hash, "iteration": iteration},
                    )
                )

                result = repl.execute(code)

                self._event_log.append(
                    REPLExecFinished(
                        run_id=rid,
                        seq=seq.next(),
                        payload={
                            "success": result.success,
                            "stdout_length": len(result.stdout),
                            "has_final": result.state.has_final,
                            "variables": list(result.state.variables.keys()),
                            "error_type": result.error_type,
                            "error_message": result.error_message,
                        },
                    )
                )

                # Record step for stop condition tracking
                if self._stop_checker is not None:
                    if result.success:
                        self._stop_checker.record_task_success()
                    else:
                        self._stop_checker.record_task_failure()

                # 5f. Append code + metadata to history
                history.append(LMMessage(role="assistant", content=code))
                metadata = self._format_metadata(
                    iteration, result, cfg.max_stdout_in_history
                )
                history.append(LMMessage(role="user", content=metadata))

                # 5g. Emit RLMIterationFinished
                self._event_log.append(
                    RLMIterationFinished(
                        run_id=rid,
                        seq=seq.next(),
                        payload={
                            "iteration": iteration,
                            "has_final": result.state.has_final,
                            "success": result.success,
                        },
                    )
                )

                # 5h. If FINAL is set, break
                if result.state.has_final:
                    outcome = "SUCCEEDED"
                    final_result = result.state.final_value
                    break

        except BudgetExceededError:
            outcome = "BUDGET_EXCEEDED"
            # Sync seq with budget manager (it emitted BudgetExceeded event)
            if self._budget_manager is not None:
                seq.value = max(seq.value, self._budget_manager._seq)  # noqa: SLF001
        except Exception as exc:
            outcome = "FAILED"
            logger.exception("RecursiveExecutor failed: %s", exc)

        # 6. Emit RunFinished
        self._event_log.append(
            RunFinished(
                run_id=rid,
                seq=seq.next(),
                payload={
                    "executor": "RecursiveExecutor",
                    "outcome": outcome,
                    "final_result": final_result,
                },
            )
        )

        return rid, final_result

    def _build_lm_query_closure(
        self, run_id: RunId, config: RLMConfig, seq: _SeqCounter
    ) -> Callable[[str], str]:
        """Build the lm_query function injected into the REPL namespace."""
        event_log = self._event_log
        lm_provider = self._lm_provider
        budget_manager = self._budget_manager
        # Track recursion depth locally for the closure
        depth = [0]

        def lm_query(query_str: str) -> str:
            """Query the language model from within REPL code."""
            if depth[0] >= config.max_recursion_depth:
                raise RuntimeError(
                    f"Max recursion depth ({config.max_recursion_depth}) exceeded"
                )

            depth[0] += 1

            # Increment recursion depth in budget
            if budget_manager is not None:
                budget_manager.set_seq(seq.value)
                budget_manager.apply(BudgetDelta(recursion_depth_change=1))
                seq.value = max(seq.value, budget_manager._seq)  # noqa: SLF001

            try:
                event_log.append(
                    LMCallStarted(
                        run_id=run_id,
                        seq=seq.next(),
                        payload={
                            "call_type": "sub_lm_query",
                            "query_length": len(query_str),
                        },
                    )
                )

                start = time.monotonic()
                response = lm_provider.complete(
                    [LMMessage(role="user", content=query_str)]
                )
                duration = time.monotonic() - start

                event_log.append(
                    LMCallFinished(
                        run_id=run_id,
                        seq=seq.next(),
                        payload={
                            "call_type": "sub_lm_query",
                            "tokens_used": response.tokens_used,
                            "duration_seconds": duration,
                        },
                    )
                )

                # Record tokens in budget
                if budget_manager is not None:
                    budget_manager.set_seq(seq.value)
                    budget_manager.record_tokens(response.tokens_used)
                    seq.value = max(seq.value, budget_manager._seq)  # noqa: SLF001

                return response.content
            finally:
                depth[0] -= 1
                if budget_manager is not None:
                    budget_manager.set_seq(seq.value)
                    budget_manager.apply(BudgetDelta(recursion_depth_change=-1))
                    seq.value = max(seq.value, budget_manager._seq)  # noqa: SLF001

        return lm_query

    @staticmethod
    def _format_metadata(
        iteration: int,
        result: object,
        max_stdout: int,
    ) -> str:
        """Format REPL execution metadata for history."""
        # result is a REPLResult — access attributes directly
        state = result.state  # type: ignore[attr-defined]
        stdout = result.stdout  # type: ignore[attr-defined]
        success = result.success  # type: ignore[attr-defined]
        error_type = result.error_type  # type: ignore[attr-defined]
        error_message = result.error_message  # type: ignore[attr-defined]

        lines = [f"[REPL] iteration={iteration}"]
        lines.append(f"  variables: {list(state.variables.keys())}")

        if stdout:
            truncated = stdout[:max_stdout]
            lines.append(f"  stdout ({len(stdout)} chars): {truncated}")

        if not success:
            lines.append(f"  error: {error_type}: {error_message}")

        if state.has_final:
            lines.append(f"  FINAL is set: {state.final_value}")

        return "\n".join(lines)
