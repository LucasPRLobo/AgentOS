"""REPL environment — sandboxed code execution with namespace isolation."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.errors import REPLExecutionError

_MAX_REPR_LEN = 200


class REPLState(BaseModel):
    """Snapshot of the REPL namespace state."""

    variables: dict[str, str] = Field(
        default_factory=dict, description="Variable name → truncated repr"
    )
    has_final: bool = Field(
        default=False, description="Whether FINAL variable is set"
    )
    final_value: str | None = Field(
        default=None, description="String repr of FINAL if set"
    )
    iteration_count: int = Field(ge=0, default=0)


class REPLResult(BaseModel):
    """Result of a single REPL execution."""

    stdout: str = ""
    stderr: str = ""
    success: bool = True
    error_type: str | None = None
    error_message: str | None = None
    state: REPLState = Field(default_factory=REPLState)


def _default_safe_builtins() -> dict[str, Any]:
    """Return a whitelist of safe builtins for sandboxed execution."""
    import builtins

    allowed = [
        "abs", "all", "any", "bool", "chr", "dict", "enumerate", "filter",
        "float", "format", "frozenset", "getattr", "hasattr", "hash", "hex",
        "id", "int", "isinstance", "issubclass", "iter", "len", "list", "map",
        "max", "min", "next", "oct", "ord", "pow", "print", "range", "repr",
        "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple",
        "type", "zip",
    ]
    return {name: getattr(builtins, name) for name in allowed}


# Names that are blocked even if somehow injected
_BLOCKED_NAMES = frozenset({"import", "open", "eval", "exec", "__import__"})


class REPLEnvironment:
    """Namespace-isolated Python REPL with builtin whitelist.

    Code is executed via ``exec()`` with a restricted ``__builtins__`` dict.
    The prompt ``P`` is loaded as an initial variable, and helper functions
    like ``lm_query`` are injected into the namespace.
    """

    def __init__(
        self,
        *,
        initial_vars: dict[str, Any] | None = None,
        injected_functions: dict[str, Callable[..., Any]] | None = None,
        allowed_builtins: dict[str, Any] | None = None,
    ) -> None:
        self._builtins = allowed_builtins or _default_safe_builtins()
        self._namespace: dict[str, Any] = {"__builtins__": self._builtins}
        self._iteration_count = 0

        if initial_vars:
            self._namespace.update(initial_vars)
        if injected_functions:
            self._namespace.update(injected_functions)

    def execute(self, code: str) -> REPLResult:
        """Execute code in the sandboxed namespace.

        Captures stdout/stderr, detects errors, and returns a snapshot of state.
        """
        self._iteration_count += 1

        # Block dangerous patterns
        violation = self._check_code_safety(code)
        if violation:
            return REPLResult(
                success=False,
                error_type="REPLExecutionError",
                error_message=violation,
                state=self.snapshot(),
            )

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(code, self._namespace)  # noqa: S102
        except Exception as exc:
            return REPLResult(
                stdout=stdout_buf.getvalue(),
                stderr=stderr_buf.getvalue(),
                success=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
                state=self.snapshot(),
            )

        return REPLResult(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            success=True,
            state=self.snapshot(),
        )

    def snapshot(self) -> REPLState:
        """Return a snapshot of the current namespace state."""
        variables: dict[str, str] = {}
        for name, value in self._namespace.items():
            if name.startswith("_") or callable(value):
                continue
            r = repr(value)
            if len(r) > _MAX_REPR_LEN:
                r = r[:_MAX_REPR_LEN] + "..."
            variables[name] = r

        has_final = "FINAL" in self._namespace
        final_value = str(self._namespace["FINAL"]) if has_final else None

        return REPLState(
            variables=variables,
            has_final=has_final,
            final_value=final_value,
            iteration_count=self._iteration_count,
        )

    def get_variable(self, name: str) -> Any:
        """Get a variable from the namespace."""
        if name not in self._namespace:
            raise REPLExecutionError(f"Variable '{name}' not found in REPL namespace")
        return self._namespace[name]

    def set_variable(self, name: str, value: Any) -> None:
        """Set a variable in the namespace."""
        self._namespace[name] = value

    @staticmethod
    def _check_code_safety(code: str) -> str | None:
        """Check code for blocked patterns. Returns violation message or None."""
        # Block import statements
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                return f"Import statements are not allowed: {stripped}"

        # Block dangerous builtins used as function calls
        for name in _BLOCKED_NAMES:
            # Check for direct calls like open(...), __import__(...)
            if name + "(" in code:
                return f"Blocked function call: {name}()"

        return None
