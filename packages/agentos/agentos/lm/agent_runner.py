"""AgentRunner — tool-calling agent execution loop with full governance."""

from __future__ import annotations

import hashlib
import logging
import time
from enum import StrEnum

from pydantic import ValidationError

from agentos.core.errors import BudgetExceededError, PermissionDeniedError
from agentos.core.identifiers import RunId, generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.governance.permissions import PermissionsEngine
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.lm.acceptance import AcceptanceChecker
from agentos.lm.agent_action import AgentAction, AgentActionType, parse_agent_action
from agentos.lm.agent_config import AgentConfig
from agentos.lm.provider import BaseLMProvider, LMMessage
from agentos.lm.tool_descriptions import build_tool_descriptions
from agentos.runtime.event_log import EventLog
from agentos.schemas.events import (
    AgentStepFinished,
    AgentStepStarted,
    LMCallFinished,
    LMCallStarted,
    RunFinished,
    RunStarted,
    ToolCallFinished,
    ToolCallStarted,
)
from agentos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentOutcome(StrEnum):
    """Possible outcomes of an agent run."""

    SUCCEEDED = "SUCCEEDED"
    MAX_STEPS = "MAX_STEPS"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    STOPPED = "STOPPED"
    TOO_MANY_ERRORS = "TOO_MANY_ERRORS"
    FAILED = "FAILED"


class _SeqCounter:
    """Mutable sequence counter shared between executor methods."""

    __slots__ = ("value",)

    def __init__(self, start: int = 0) -> None:
        self.value = start

    def next(self) -> int:
        v = self.value
        self.value += 1
        return v


class AgentRunner:
    """Executes an observe-plan-act-verify agent loop with tool calling.

    The LM selects named tools from a registry via structured JSON responses.
    AgentOS dispatches those calls through the full governance stack
    (permissions, budget, events).
    """

    def __init__(
        self,
        event_log: EventLog,
        lm_provider: BaseLMProvider,
        tool_registry: ToolRegistry,
        *,
        budget_manager: BudgetManager | None = None,
        stop_checker: StopConditionChecker | None = None,
        permissions_engine: PermissionsEngine | None = None,
        acceptance_checker: AcceptanceChecker | None = None,
    ) -> None:
        self._event_log = event_log
        self._lm_provider = lm_provider
        self._tool_registry = tool_registry
        self._budget_manager = budget_manager
        self._stop_checker = stop_checker
        self._permissions_engine = permissions_engine
        self._acceptance_checker = acceptance_checker

    def run(
        self,
        task_description: str,
        *,
        run_id: RunId | None = None,
        config: AgentConfig | None = None,
    ) -> tuple[RunId, str | None]:
        """Execute the agent loop on the given task.

        Returns (run_id, final_result) where final_result is the agent's
        result string if it finished, or None otherwise.
        """
        cfg = config or AgentConfig()
        rid = run_id or generate_run_id()
        seq = _SeqCounter(0)

        # Emit RunStarted
        self._event_log.append(
            RunStarted(
                run_id=rid,
                seq=seq.next(),
                payload={"executor": "AgentRunner", "task_length": len(task_description)},
            )
        )

        # Build initial history
        tool_desc = build_tool_descriptions(self._tool_registry)
        system_content = f"{cfg.system_prompt}\n\n# Available Tools\n\n{tool_desc}"
        history: list[LMMessage] = [
            LMMessage(role="system", content=system_content),
            LMMessage(role="user", content=task_description),
        ]

        outcome = AgentOutcome.MAX_STEPS
        final_result: str | None = None
        consecutive_errors = 0

        try:
            for step in range(1, cfg.max_steps + 1):
                # Budget check
                if self._budget_manager is not None:
                    self._budget_manager.set_seq(seq.value)
                    self._budget_manager.check()
                    seq.value = max(seq.value, self._budget_manager._seq)  # noqa: SLF001

                # Stop condition check
                if self._stop_checker is not None:
                    stop_reason = self._stop_checker.check(seq.next())
                    if stop_reason is not None:
                        outcome = AgentOutcome.STOPPED
                        break

                # Emit AgentStepStarted
                self._event_log.append(
                    AgentStepStarted(
                        run_id=rid,
                        seq=seq.next(),
                        payload={"step": step},
                    )
                )

                # LM call
                self._event_log.append(
                    LMCallStarted(
                        run_id=rid,
                        seq=seq.next(),
                        payload={
                            "call_type": "agent_step",
                            "step": step,
                            "history_length": len(history),
                        },
                    )
                )

                lm_start = time.monotonic()
                response = self._lm_provider.complete(history)
                lm_duration = time.monotonic() - lm_start

                self._event_log.append(
                    LMCallFinished(
                        run_id=rid,
                        seq=seq.next(),
                        payload={
                            "call_type": "agent_step",
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

                # Parse action
                try:
                    action = parse_agent_action(response.content)
                except ValueError as e:
                    consecutive_errors += 1
                    logger.warning("Parse error on step %d: %s", step, e)
                    history.append(LMMessage(role="assistant", content=response.content))
                    history.append(
                        LMMessage(
                            role="user",
                            content=(
                                f"[ERROR] Failed to parse your response as JSON: {e}\n"
                                "Please respond with a valid JSON object."
                            ),
                        )
                    )
                    self._event_log.append(
                        AgentStepFinished(
                            run_id=rid,
                            seq=seq.next(),
                            payload={"step": step, "result": "parse_error"},
                        )
                    )
                    if consecutive_errors >= cfg.max_consecutive_errors:
                        outcome = AgentOutcome.TOO_MANY_ERRORS
                        break
                    continue

                # Reset consecutive errors on successful parse
                consecutive_errors = 0

                # Handle finish action
                if action.action == AgentActionType.FINISH:
                    result_str = action.result or ""
                    # Check acceptance criteria
                    if self._acceptance_checker is not None:
                        all_passed, results = self._acceptance_checker.check_all(
                            {"result": result_str, "run_id": rid}
                        )
                        if not all_passed:
                            failed = [r for r in results if not r.passed]
                            feedback = "Acceptance criteria not met:\n" + "\n".join(
                                f"- {r.name}: {r.message}" for r in failed
                            )
                            history.append(
                                LMMessage(role="assistant", content=response.content)
                            )
                            history.append(LMMessage(role="user", content=feedback))
                            self._event_log.append(
                                AgentStepFinished(
                                    run_id=rid,
                                    seq=seq.next(),
                                    payload={
                                        "step": step,
                                        "result": "acceptance_failed",
                                    },
                                )
                            )
                            continue

                    outcome = AgentOutcome.SUCCEEDED
                    final_result = result_str
                    self._event_log.append(
                        AgentStepFinished(
                            run_id=rid,
                            seq=seq.next(),
                            payload={"step": step, "result": "finish"},
                        )
                    )
                    break

                # Handle tool_call action
                step_result = self._execute_tool_call(
                    action, rid, seq, history, response.content, step
                )

                self._event_log.append(
                    AgentStepFinished(
                        run_id=rid,
                        seq=seq.next(),
                        payload={"step": step, "result": step_result},
                    )
                )

        except BudgetExceededError:
            outcome = AgentOutcome.BUDGET_EXCEEDED
            if self._budget_manager is not None:
                seq.value = max(seq.value, self._budget_manager._seq)  # noqa: SLF001
        except Exception as exc:
            outcome = AgentOutcome.FAILED
            logger.exception("AgentRunner failed: %s", exc)

        # Emit RunFinished
        self._event_log.append(
            RunFinished(
                run_id=rid,
                seq=seq.next(),
                payload={
                    "executor": "AgentRunner",
                    "outcome": outcome.value,
                    "final_result": final_result,
                },
            )
        )

        return rid, final_result

    def _execute_tool_call(
        self,
        action: AgentAction,
        rid: RunId,
        seq: _SeqCounter,
        history: list[LMMessage],
        raw_response: str,
        step: int,
    ) -> str:
        """Execute a tool call action. Returns step result string."""
        tool_name = action.tool or ""
        tool_input = action.input or {}
        input_hash = hashlib.sha256(
            str(sorted(tool_input.items())).encode()
        ).hexdigest()[:16]

        # Check tool exists
        if not self._tool_registry.has(tool_name):
            history.append(LMMessage(role="assistant", content=raw_response))
            history.append(
                LMMessage(
                    role="user",
                    content=f"[ERROR] Unknown tool '{tool_name}'. Available tools: "
                    f"{', '.join(t.name for t in self._tool_registry.list_tools())}",
                )
            )
            return "unknown_tool"

        tool = self._tool_registry.lookup(tool_name)

        # Check permissions
        if self._permissions_engine is not None:
            try:
                self._permissions_engine.check(tool_name, tool.side_effect, seq.next())
            except PermissionDeniedError as e:
                history.append(LMMessage(role="assistant", content=raw_response))
                history.append(
                    LMMessage(role="user", content=f"[ERROR] Permission denied: {e}")
                )
                return "permission_denied"

        # Record tool call in budget
        if self._budget_manager is not None:
            self._budget_manager.set_seq(seq.value)
            self._budget_manager.record_tool_call()
            seq.value = max(seq.value, self._budget_manager._seq)  # noqa: SLF001

        # Record tool call for stop condition tracking
        if self._stop_checker is not None:
            self._stop_checker.record_tool_call(tool_name, input_hash)

        # Validate input
        try:
            validated_input = tool.validate_input(tool_input)
        except (ValidationError, Exception) as e:
            history.append(LMMessage(role="assistant", content=raw_response))
            history.append(
                LMMessage(
                    role="user",
                    content=f"[ERROR] Invalid input for tool '{tool_name}': {e}",
                )
            )
            return "validation_error"

        # Emit ToolCallStarted
        self._event_log.append(
            ToolCallStarted(
                run_id=rid,
                seq=seq.next(),
                payload={
                    "tool_name": tool_name,
                    "side_effect": tool.side_effect.value,
                    "input_hash": input_hash,
                },
            )
        )

        # Execute tool
        try:
            output = tool.execute(validated_input)
            output_dict = output.model_dump()
            output_hash = hashlib.sha256(
                str(sorted(output_dict.items())).encode()
            ).hexdigest()[:16]

            self._event_log.append(
                ToolCallFinished(
                    run_id=rid,
                    seq=seq.next(),
                    payload={
                        "tool_name": tool_name,
                        "success": True,
                        "output_hash": output_hash,
                    },
                )
            )

            if self._stop_checker is not None:
                self._stop_checker.record_task_success()

            # Append to history
            history.append(LMMessage(role="assistant", content=raw_response))
            history.append(
                LMMessage(
                    role="user",
                    content=f"[TOOL RESULT] {tool_name}:\n{output.model_dump_json(indent=2)}",
                )
            )
            return "tool_success"

        except Exception as e:
            self._event_log.append(
                ToolCallFinished(
                    run_id=rid,
                    seq=seq.next(),
                    payload={
                        "tool_name": tool_name,
                        "success": False,
                        "error": str(e),
                    },
                )
            )

            if self._stop_checker is not None:
                self._stop_checker.record_task_failure()

            history.append(LMMessage(role="assistant", content=raw_response))
            history.append(
                LMMessage(
                    role="user",
                    content=f"[ERROR] Tool '{tool_name}' failed: {e}",
                )
            )
            return "tool_error"
