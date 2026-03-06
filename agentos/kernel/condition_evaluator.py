"""Safe expression evaluator for conditional branching.

Evaluates condition expressions against TaskOutput fields in a
restricted namespace. No imports, no dangerous builtins — only
safe accessors for task output data.
"""

from __future__ import annotations

from agentos.schemas.task import TaskOutput


# Builtins allowed in condition expressions.
_SAFE_BUILTINS = {
    "len": len,
    "any": any,
    "all": all,
    "True": True,
    "False": False,
    "None": None,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "abs": abs,
    "min": min,
    "max": max,
}


class ConditionEvaluationError(Exception):
    """Raised when a condition expression cannot be evaluated safely."""


def evaluate_condition(expression: str, output: TaskOutput) -> bool:
    """Evaluate a condition expression against a TaskOutput.

    The expression has access to:
      - ``output``: the full TaskOutput object
      - ``summary``: output.summary (str)
      - ``status``: str(output.status)
      - ``findings``: list of finding strings from key_findings
      - ``files``: list of file path strings from files_produced
      - ``open_questions``: output.open_questions
      - ``iteration``: output.iteration

    Returns True if the condition is met, False otherwise.

    Raises ConditionEvaluationError on invalid or unsafe expressions.
    """
    if not expression or not expression.strip():
        raise ConditionEvaluationError("Empty condition expression")

    # Build restricted namespace
    findings = [f.finding for f in output.key_findings]
    files = [f.path for f in output.files_produced]

    namespace = {
        "__builtins__": _SAFE_BUILTINS,
        "output": output,
        "summary": output.summary,
        "status": str(output.status),
        "findings": findings,
        "files": files,
        "open_questions": output.open_questions,
        "iteration": output.iteration,
    }

    try:
        result = eval(expression, namespace)  # noqa: S307
    except Exception as exc:
        raise ConditionEvaluationError(
            f"Failed to evaluate condition {expression!r}: {exc}"
        ) from exc

    return bool(result)
