"""Tests for REPL environment — sandboxed execution with namespace isolation."""

import pytest

from agentos.core.errors import REPLExecutionError
from agentos.lm.repl import REPLEnvironment, REPLResult, REPLState


class TestREPLState:
    def test_defaults(self) -> None:
        state = REPLState()
        assert state.variables == {}
        assert state.has_final is False
        assert state.final_value is None
        assert state.iteration_count == 0

    def test_with_final(self) -> None:
        state = REPLState(has_final=True, final_value="42", iteration_count=3)
        assert state.has_final is True
        assert state.final_value == "42"


class TestREPLResult:
    def test_success_result(self) -> None:
        result = REPLResult(stdout="hello\n", success=True)
        assert result.success is True
        assert result.error_type is None

    def test_error_result(self) -> None:
        result = REPLResult(
            success=False,
            error_type="ZeroDivisionError",
            error_message="division by zero",
        )
        assert result.success is False
        assert result.error_type == "ZeroDivisionError"


class TestREPLEnvironment:
    def test_simple_execution(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("x = 1 + 2")
        assert result.success is True
        assert repl.get_variable("x") == 3

    def test_persistent_state_across_calls(self) -> None:
        repl = REPLEnvironment()
        repl.execute("x = 10")
        result = repl.execute("y = x * 2")
        assert result.success is True
        assert repl.get_variable("y") == 20

    def test_stdout_capture(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("print('hello world')")
        assert result.success is True
        assert "hello world" in result.stdout

    def test_error_handling_zero_division(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("x = 1 / 0")
        assert result.success is False
        assert result.error_type == "ZeroDivisionError"
        assert "division by zero" in result.error_message

    def test_final_variable_detection(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("FINAL = 'the answer is 42'")
        assert result.success is True
        assert result.state.has_final is True
        assert result.state.final_value == "the answer is 42"

    def test_no_final_by_default(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("x = 42")
        assert result.state.has_final is False
        assert result.state.final_value is None

    def test_initial_variables(self) -> None:
        repl = REPLEnvironment(initial_vars={"P": "What is 2+2?"})
        assert repl.get_variable("P") == "What is 2+2?"
        result = repl.execute("answer = len(P)")
        assert result.success is True
        assert repl.get_variable("answer") == len("What is 2+2?")

    def test_injected_functions(self) -> None:
        def mock_lm_query(text: str) -> str:
            return f"Response to: {text}"

        repl = REPLEnvironment(injected_functions={"lm_query": mock_lm_query})
        result = repl.execute("result = lm_query('hello')")
        assert result.success is True
        assert repl.get_variable("result") == "Response to: hello"

    def test_sandbox_blocks_import(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("import os")
        assert result.success is False
        assert "Import statements are not allowed" in result.error_message

    def test_sandbox_blocks_from_import(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("from os import path")
        assert result.success is False
        assert "Import statements are not allowed" in result.error_message

    def test_sandbox_blocks_open(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("f = open('/etc/passwd')")
        assert result.success is False
        assert "Blocked function call: open()" in result.error_message

    def test_sandbox_blocks_dunder_import(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("os = __import__('os')")
        assert result.success is False
        assert "Blocked function call" in result.error_message

    def test_iteration_count_tracking(self) -> None:
        repl = REPLEnvironment()
        repl.execute("x = 1")
        repl.execute("y = 2")
        result = repl.execute("z = 3")
        assert result.state.iteration_count == 3

    def test_get_variable(self) -> None:
        repl = REPLEnvironment()
        repl.execute("x = 42")
        assert repl.get_variable("x") == 42

    def test_get_variable_not_found(self) -> None:
        repl = REPLEnvironment()
        with pytest.raises(REPLExecutionError, match="not found"):
            repl.get_variable("nonexistent")

    def test_set_variable(self) -> None:
        repl = REPLEnvironment()
        repl.set_variable("x", 99)
        result = repl.execute("y = x + 1")
        assert result.success is True
        assert repl.get_variable("y") == 100

    def test_snapshot_truncates_long_values(self) -> None:
        repl = REPLEnvironment()
        repl.execute("x = 'a' * 500")
        state = repl.snapshot()
        assert len(state.variables["x"]) <= 203  # 200 + "..."

    def test_snapshot_excludes_callables(self) -> None:
        def my_func() -> None:
            pass

        repl = REPLEnvironment(injected_functions={"my_func": my_func})
        state = repl.snapshot()
        assert "my_func" not in state.variables

    def test_snapshot_excludes_private_vars(self) -> None:
        repl = REPLEnvironment()
        repl.execute("_private = 42")
        state = repl.snapshot()
        assert "_private" not in state.variables

    def test_multiple_statements(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("x = 1\ny = 2\nz = x + y")
        assert result.success is True
        assert repl.get_variable("z") == 3

    def test_allowed_builtins_work(self) -> None:
        repl = REPLEnvironment()
        result = repl.execute("x = len([1, 2, 3])")
        assert result.success is True
        assert repl.get_variable("x") == 3

        result = repl.execute("y = sorted([3, 1, 2])")
        assert result.success is True
        assert repl.get_variable("y") == [1, 2, 3]

        result = repl.execute("z = sum(range(5))")
        assert result.success is True
        assert repl.get_variable("z") == 10
