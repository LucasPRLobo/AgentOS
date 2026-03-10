"""Safe expression evaluator for conditional branching.

Evaluates condition expressions against TaskOutput fields using an
AST-based evaluator. No eval() — only safe node types are allowed.
"""

from __future__ import annotations

import ast
import operator

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

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

_BOOL_OPS = {
    ast.And: all,
    ast.Or: any,
}

_UNARY_OPS = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_ALLOWED_NODES = (
    ast.Expression,
    ast.Compare,
    ast.BoolOp,
    ast.UnaryOp,
    ast.BinOp,
    ast.Name,
    ast.Constant,
    ast.Attribute,
    ast.Call,
    ast.Subscript,
    ast.List,
    ast.Tuple,
    ast.Load,
    ast.Store,
    ast.Index,
    ast.IfExp,
    ast.GeneratorExp,
    ast.ListComp,
    ast.comprehension,
    # Comparison operators
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    # Boolean operators
    ast.And,
    ast.Or,
    # Unary operators
    ast.Not,
    ast.USub,
    ast.UAdd,
    # Binary operators
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
)

_ALLOWED_CALLABLES = frozenset({len, any, all, str, int, float, bool, list, abs, min, max})


class ConditionEvaluationError(Exception):
    """Raised when a condition expression cannot be evaluated safely."""


class _SafeEvaluator(ast.NodeVisitor):
    """AST-based expression evaluator that only allows safe operations."""

    def __init__(self, namespace: dict):
        self._ns = namespace

    def evaluate(self, expression: str):
        tree = ast.parse(expression, mode="eval")
        self._validate(tree)
        return self._eval_node(tree.body)

    def _validate(self, node: ast.AST) -> None:
        """Reject any node type not in the allow list."""
        for child in ast.walk(node):
            if not isinstance(child, _ALLOWED_NODES):
                raise ValueError(f"Unsafe expression node: {type(child).__name__}")

    def _eval_node(self, node: ast.AST):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in _SAFE_BUILTINS:
                return _SAFE_BUILTINS[node.id]
            if node.id in self._ns:
                return self._ns[node.id]
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, ast.Attribute):
            value = self._eval_node(node.value)
            return getattr(value, node.attr)
        if isinstance(node, ast.Subscript):
            value = self._eval_node(node.value)
            key = self._eval_node(node.slice)
            return value[key]
        if isinstance(node, ast.UnaryOp):
            op_fn = _UNARY_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
            return op_fn(self._eval_node(node.operand))
        if isinstance(node, ast.BinOp):
            op_fn = _BIN_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported binary op: {type(node.op).__name__}")
            return op_fn(self._eval_node(node.left), self._eval_node(node.right))
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                op_fn = _COMPARE_OPS.get(type(op))
                if op_fn is None:
                    raise ValueError(f"Unsupported comparison: {type(op).__name__}")
                right = self._eval_node(comparator)
                if not op_fn(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [self._eval_node(v) for v in node.values]
            op_fn = _BOOL_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported bool op: {type(node.op).__name__}")
            return op_fn(values)
        if isinstance(node, ast.Call):
            func = self._eval_node(node.func)
            args = [self._eval_node(a) for a in node.args]
            # Allow whitelisted builtins
            if func in _ALLOWED_CALLABLES:
                return func(*args)
            # Allow bound methods on safe types (str, list, tuple, dict)
            if callable(func) and isinstance(node.func, ast.Attribute):
                owner = self._eval_node(node.func.value)
                if isinstance(owner, (str, list, tuple, dict, set, frozenset)):
                    return func(*args)
            raise ValueError(f"Function not allowed: {func}")
        if isinstance(node, ast.IfExp):
            if self._eval_node(node.test):
                return self._eval_node(node.body)
            return self._eval_node(node.orelse)
        if isinstance(node, ast.List):
            return [self._eval_node(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(e) for e in node.elts)
        if isinstance(node, ast.GeneratorExp):
            return self._eval_generator(node)
        if isinstance(node, ast.ListComp):
            return list(self._eval_generator(node))
        raise ValueError(f"Unsupported node: {type(node).__name__}")

    def _eval_generator(self, node: ast.GeneratorExp | ast.ListComp):
        """Evaluate a generator expression or list comprehension."""
        # Only support single-level comprehensions for safety
        if len(node.generators) != 1:
            raise ValueError("Only single-level comprehensions are supported")

        comp = node.generators[0]
        iterable = self._eval_node(comp.iter)

        def _gen():
            for item in iterable:
                # Temporarily bind the loop variable in the namespace
                target_name = comp.target.id if isinstance(comp.target, ast.Name) else None
                if target_name is None:
                    raise ValueError("Only simple loop variables are supported")
                old = self._ns.get(target_name, _SENTINEL)
                self._ns[target_name] = item
                try:
                    # Check all if-clauses
                    if all(self._eval_node(if_clause) for if_clause in comp.ifs):
                        yield self._eval_node(node.elt)
                finally:
                    if old is _SENTINEL:
                        self._ns.pop(target_name, None)
                    else:
                        self._ns[target_name] = old

        return _gen()


_SENTINEL = object()


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
        "output": output,
        "summary": output.summary,
        "status": str(output.status),
        "findings": findings,
        "files": files,
        "open_questions": output.open_questions,
        "iteration": output.iteration,
    }

    try:
        evaluator = _SafeEvaluator(namespace)
        result = evaluator.evaluate(expression)
    except Exception as exc:
        raise ConditionEvaluationError(
            f"Failed to evaluate condition {expression!r}: {exc}"
        ) from exc

    return bool(result)
