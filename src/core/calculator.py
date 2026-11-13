"""Deterministic AST-whitelist compliance calculator (Phase 8C stretch feature).

Evaluates compliance arithmetic strictly using Python's ``ast`` module with an
explicit node and operator whitelist. ``eval`` and ``exec`` are never called.

Security invariants:
    - No attribute access, imports, subscripts, or arbitrary callables.
    - Passages are filtered with :func:`src.core.security.enforce_role_visibility`
      before any numeric operand is extracted.
    - If any required operand is absent from role-permitted passages, the tool
      refuses explicitly and reports which input is missing.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any

from pydantic import BaseModel, Field

from src.core.security import enforce_role_visibility, normalize_role


class UnsafeExpressionError(ValueError):
    """Raised when an expression violates the calculator AST whitelist."""


class CalculatorInput(BaseModel):
    """Single passage-grounded or user-supplied numeric operand."""

    name: str
    value: float
    unit: str = ""
    chunk_id: str | None = None
    source_label: str = ""


class CalculationResult(BaseModel):
    """Structured calculation output or missing-input refusal."""

    triggered: bool = False
    refused: bool = False
    refusal_reason: str = ""
    formula: str = ""
    inputs: list[CalculatorInput] = Field(default_factory=list)
    result: float | None = None
    unit: str = ""
    formatted_result: str = ""
    formatted_summary: str = ""
    rbac_dropped_passages: int = 0


_BINARY_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_SAFE_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sum": sum,
}

_DANGEROUS_PATTERN = re.compile(
    r"(?:__|import\s*\(|exec\s*\(|eval\s*\(|open\s*\(|os\.|sys\.|subprocess|lambda)",
    re.IGNORECASE,
)


def _eval_ast_node(node: ast.AST) -> float:
    """Recursively evaluate an already-parsed AST expression under strict whitelist rules."""
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeExpressionError(f"Disallowed constant type: {type(node.value).__name__}")
        return float(node.value)

    if isinstance(node, ast.UnaryOp):
        op_fn = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise UnsafeExpressionError(f"Disallowed unary operator: {type(node.op).__name__}")
        return float(op_fn(_eval_ast_node(node.operand)))

    if isinstance(node, ast.BinOp):
        op_fn = _BINARY_OPS.get(type(node.op))
        if op_fn is None:
            raise UnsafeExpressionError(f"Disallowed binary operator: {type(node.op).__name__}")
        left = _eval_ast_node(node.left)
        right = _eval_ast_node(node.right)
        if isinstance(node.op, (ast.Div, ast.Mod)) and right == 0.0:
            raise UnsafeExpressionError("Division or modulo by zero is not permitted.")
        if isinstance(node.op, ast.Pow) and (abs(right) > 100.0 or abs(left) > 1e9):
            raise UnsafeExpressionError("Exponent exceeds safe calculation bounds.")
        return float(op_fn(left, right))

    if isinstance(node, ast.Call):
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not allowed in calculator functions.")
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCTIONS:
            raise UnsafeExpressionError("Function call is not in the calculator whitelist.")
        fn = _SAFE_FUNCTIONS[node.func.id]
        if node.func.id == "sum":
            if len(node.args) != 1 or not isinstance(node.args[0], (ast.List, ast.Tuple)):
                raise UnsafeExpressionError("sum() requires a literal list or tuple of numbers.")
            values = [_eval_ast_node(elt) for elt in node.args[0].elts]
            return float(sum(values))
        if not node.args:
            raise UnsafeExpressionError(f"{node.func.id}() requires at least one argument.")
        evaluated_args = [_eval_ast_node(arg) for arg in node.args]
        if node.func.id == "round":
            if len(evaluated_args) == 1:
                return float(round(evaluated_args[0]))
            if len(evaluated_args) == 2:
                return float(round(evaluated_args[0], int(evaluated_args[1])))
            raise UnsafeExpressionError("round() accepts 1 or 2 arguments.")
        return float(fn(*evaluated_args))

    raise UnsafeExpressionError(f"Disallowed AST node: {type(node).__name__}")


def safe_eval_arithmetic(expr: str) -> float:
    """Safely evaluate an arithmetic expression string using a strict AST whitelist."""
    if not expr or not isinstance(expr, str):
        raise UnsafeExpressionError("Expression must be a non-empty string.")
    if len(expr) > 256:
        raise UnsafeExpressionError("Expression exceeds maximum allowed length.")
    if _DANGEROUS_PATTERN.search(expr):
        raise UnsafeExpressionError("Expression contains blocked Python constructs.")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"Invalid arithmetic syntax: {exc.msg}") from exc
    return round(_eval_ast_node(tree), 6)


# ==============================================================================
# Passage Operand Extraction (strictly over role-filtered passages)
# ==============================================================================

_OPERAND_PATTERNS: list[tuple[str, str, re.Pattern[str], str]] = [
    (
        "cet1_minimum",
        "CET1 minimum ratio",
        re.compile(r"(?:CET1|Common Equity Tier 1)[^.%\n]{0,60}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "tier1_minimum",
        "Tier 1 minimum ratio",
        re.compile(r"Tier\s*1\s+(?:Capital\s+)?(?:ratio\s+)?(?:is|at\s+least|minimum\s+(?:requirement\s+of\s+)?)?[^.%\n]{0,40}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "total_capital_minimum",
        "Total Capital minimum ratio",
        re.compile(r"Total\s+Capital(?:\s+ratio)?[^.%\n]{0,45}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "capital_conservation_buffer",
        "Capital Conservation Buffer (CCB)",
        re.compile(r"(?:Capital Conservation Buffer|\bCCB\b)[^.%\n]{0,60}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "lcr_minimum",
        "LCR minimum requirement",
        re.compile(r"(?:LCR|Liquidity Coverage Ratio)[^.%\n]{0,60}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "nsfr_minimum",
        "NSFR minimum requirement",
        re.compile(r"(?:NSFR|Net Stable Funding Ratio)[^.%\n]{0,60}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "beneficial_ownership_threshold",
        "Beneficial ownership threshold",
        re.compile(r"(?:beneficial\s+owner(?:ship)?|owns\s+or\s+controls|more\s+than)[^.%\n]{0,45}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "unhedged_exposure_threshold",
        "Unhedged FX exposure escalation threshold",
        re.compile(r"unhedged[^.\n]{0,70}?[£$€]\s*(\d+(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
        "GBP",
    ),
    (
        "deposit_balance_threshold",
        "BCOBS notice deposit threshold",
        re.compile(r"(?:balance\s+of\s+over|exceeding|over)\s+[£]\s*(\d+(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
        "GBP",
    ),
    (
        "interest_rate_drop_threshold",
        "BCOBS material rate reduction threshold",
        re.compile(r"(?:reduction|drop|decrease)[^.%\n]{0,40}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
        "%",
    ),
    (
        "preclearance_days",
        "Personal trading pre-clearance window",
        re.compile(r"(\d+)-day\s+pre-clearance|pre-clearance[^.\n]{0,30}?(\d+)\s+days", re.IGNORECASE),
        "days",
    ),
    (
        "holding_period_days",
        "Minimum security holding period",
        re.compile(r"(?:hold|holding\s+period)[^.\n]{0,40}?(\d+)\s+calendar\s+days", re.IGNORECASE),
        "days",
    ),
    (
        "secondary_liquidity_deficit",
        "Audit secondary liquidity deficit",
        re.compile(
            r"(?:intra-month\s+deficit\s+of\s+|deficit\s+of\s+)(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s+(?:deficit|reduction\s+in\s+secondary\s+liquidity)",
            re.IGNORECASE,
        ),
        "%",
    ),
]


def _extract_passage_operands(
    permitted_passages: list[dict[str, Any]],
) -> dict[str, CalculatorInput]:
    """Extract named numeric inputs with chunk citations from permitted passages."""
    found: dict[str, CalculatorInput] = {}
    for passage in permitted_passages:
        cid = str(passage.get("chunk_id") or "")
        text = str(passage.get("text_content") or "")
        if not text:
            continue
        for key, label, pattern, unit in _OPERAND_PATTERNS:
            if key in found:
                continue
            match = pattern.search(text)
            if match:
                raw_num = next((g for g in match.groups() if g is not None), "")
                try:
                    val = float(raw_num.replace(",", ""))
                except ValueError:
                    continue
                found[key] = CalculatorInput(
                    name=label,
                    value=val,
                    unit=unit,
                    chunk_id=cid or None,
                    source_label=key,
                )
    return found


def _format_value(value: float, unit: str) -> str:
    """Format numeric calculator result concisely with optional unit."""
    if abs(value - round(value)) < 1e-6:
        num_str = f"{int(round(value)):,}" if abs(value) >= 1000 else f"{value:.1f}"
    else:
        num_str = f"{value:,.2f}" if abs(value) >= 1000 else f"{round(value, 4):g}"
    if unit == "%":
        return f"{num_str}%"
    if unit == "GBP":
        return f"£{num_str}"
    if unit:
        return f"{num_str} {unit}"
    return num_str


def _detect_user_amount(query: str) -> float | None:
    """Extract an explicit monetary or numeric scenario amount supplied in the query."""
    m = re.search(r"[£$€]\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(million|m|billion|bn|k)?", query, re.IGNORECASE)
    if not m:
        return None
    base = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    if suffix in ("m", "million"):
        return base * 1_000_000.0
    if suffix in ("bn", "billion"):
        return base * 1_000_000_000.0
    if suffix == "k":
        return base * 1_000.0
    return base


def _has_calculation_intent(query: str) -> bool:
    """Return True when the user query asks for arithmetic, totals, buffers, or percentages."""
    lowered = query.lower()
    keywords = (
        "calculate",
        "compute",
        "combined",
        "total ",
        "sum of",
        "plus ",
        "including the capital conservation buffer",
        "with the capital conservation buffer",
        "with ccb",
        "plus ccb",
        "excess over",
        "how much above",
        "how much capital",
        "percentage of",
        "% of",
        "difference between",
        "remaining ",
        "margin above",
    )
    if any(kw in lowered for kw in keywords):
        return True
    if re.search(r"\d+\s*[+\-*/]\s*\d+", query):
        return True
    return False


def _determine_required_operands(query: str) -> list[str]:
    """Identify which corpus compliance metrics the query explicitly asks to combine."""
    lowered = query.lower()
    reqs: list[str] = []
    if "cet1" in lowered or "common equity tier 1" in lowered:
        reqs.append("cet1_minimum")
    if re.search(r"\btier\s*1\b", lowered):
        reqs.append("tier1_minimum")
    if "total capital" in lowered:
        reqs.append("total_capital_minimum")
    if "capital conservation buffer" in lowered or re.search(r"\bccb\b", lowered):
        reqs.append("capital_conservation_buffer")
    if "lcr" in lowered or "liquidity coverage ratio" in lowered:
        reqs.append("lcr_minimum")
    if "nsfr" in lowered or "net stable funding" in lowered:
        reqs.append("nsfr_minimum")
    if "beneficial owner" in lowered or "ownership threshold" in lowered:
        reqs.append("beneficial_ownership_threshold")
    if "unhedged" in lowered:
        reqs.append("unhedged_exposure_threshold")
    if "secondary liquidity" in lowered or "liquidity deficit" in lowered:
        reqs.append("secondary_liquidity_deficit")
    if "pre-clearance" in lowered or "holding period" in lowered:
        if "pre-clearance" in lowered:
            reqs.append("preclearance_days")
        if "holding" in lowered:
            reqs.append("holding_period_days")
    return reqs


def run_compliance_calculator(
    query: str,
    passages: list[dict[str, Any]],
    role: str,
    *,
    rbac_enabled: bool = True,
) -> CalculationResult:
    """Compute a passage-grounded deterministic compliance calculation for ``query``.

    Strictly filters ``passages`` via ``enforce_role_visibility`` before inspecting
    any numeric values. If the query specifies a calculation whose inputs are absent
    from permitted passages, refuses explicitly instead of guessing.
    """
    if rbac_enabled:
        permitted_passages, dropped_count = enforce_role_visibility(
            passages, normalize_role(role)
        )
    else:
        permitted_passages = list(passages)
        dropped_count = 0

    if not _has_calculation_intent(query):
        return CalculationResult(triggered=False, rbac_dropped_passages=dropped_count)

    # Check for direct injection attempts first
    if _DANGEROUS_PATTERN.search(query):
        return CalculationResult(
            triggered=True,
            refused=True,
            refusal_reason="Refused unsafe calculation expression violating the AST arithmetic whitelist.",
            rbac_dropped_passages=dropped_count,
        )

    # Pure explicit arithmetic query without regulatory corpus metrics (e.g. "Calculate 4.5 + 2.5")
    required_keys = _determine_required_operands(query)
    explicit_math = re.search(r"(\(?\s*-?\d+(?:\.\d+)?(?:\s*[+\-*/%]\s*\(?\s*-?\d+(?:\.\d+)?\)?)+\s*\)?)", query)
    if explicit_math and not required_keys:
        expr = explicit_math.group(1).strip()
        try:
            val = safe_eval_arithmetic(expr)
        except UnsafeExpressionError as exc:
            return CalculationResult(
                triggered=True,
                refused=True,
                refusal_reason=str(exc),
                rbac_dropped_passages=dropped_count,
            )
        formatted = _format_value(val, "")
        return CalculationResult(
            triggered=True,
            refused=False,
            formula=expr,
            inputs=[],
            result=val,
            formatted_result=formatted,
            formatted_summary=f"Verified calculation: {expr} = {formatted}",
            rbac_dropped_passages=dropped_count,
        )

    available = _extract_passage_operands(permitted_passages)
    user_amount = _detect_user_amount(query)
    lowered = query.lower()

    # Check missing required regulatory operands
    missing = [key for key in required_keys if key not in available]
    if missing:
        missing_names = ", ".join(missing)
        return CalculationResult(
            triggered=True,
            refused=True,
            refusal_reason=(
                f"Calculator refused: required input(s) [{missing_names}] not found in "
                "documents available to your role."
            ),
            rbac_dropped_passages=dropped_count,
        )

    # Unknown regulatory ratio named in calculation query without matching corpus value
    if not required_keys and user_amount is None:
        return CalculationResult(
            triggered=True,
            refused=True,
            refusal_reason=(
                "Calculator refused: could not extract required numeric inputs from "
                "the passages available to your role."
            ),
            rbac_dropped_passages=dropped_count,
        )

    # Case 1: User supplies an exposure/RWA/equity amount + percentage ratio or threshold
    if user_amount is not None and required_keys:
        key = required_keys[0]
        inp = available[key]
        scenario_input = CalculatorInput(
            name="Scenario amount",
            value=user_amount,
            unit="GBP",
            chunk_id=None,
            source_label="user_query",
        )
        if inp.unit == "%":
            # e.g. CET1 + CCB if both requested on an RWA amount, else single percentage
            if len(required_keys) >= 2:
                used_inputs = [available[k] for k in required_keys]
                rate_expr = " + ".join(str(x.value) for x in used_inputs)
                formula = f"{user_amount} * ({rate_expr}) / 100"
                inputs = [scenario_input, *used_inputs]
            elif "remaining" in lowered or "after" in lowered or "less" in lowered:
                formula = f"{user_amount} * (100 - {inp.value}) / 100"
                inputs = [scenario_input, inp]
            else:
                formula = f"{user_amount} * ({inp.value} / 100)"
                inputs = [scenario_input, inp]
            unit = "GBP"
        elif inp.unit == "GBP" and ("excess" in lowered or "above" in lowered or "difference" in lowered):
            formula = f"{user_amount} - {inp.value}"
            inputs = [scenario_input, inp]
            unit = "GBP"
        else:
            return CalculationResult(
                triggered=True,
                refused=True,
                refusal_reason="Calculator refused: incompatible operand units for the requested formula.",
                rbac_dropped_passages=dropped_count,
            )

        val = safe_eval_arithmetic(formula)
        formatted = _format_value(val, unit)
        cites = ", ".join(x.chunk_id for x in inputs if x.chunk_id)
        return CalculationResult(
            triggered=True,
            refused=False,
            formula=formula,
            inputs=inputs,
            result=val,
            unit=unit,
            formatted_result=formatted,
            formatted_summary=f"Verified calculation: {formula} = {formatted} (cited: {cites})",
            rbac_dropped_passages=dropped_count,
        )

    # Case 2: Combining 2+ regulatory ratios or durations (e.g. CET1 + CCB, Tier 1 + CCB, difference)
    if len(required_keys) >= 2:
        used_inputs = [available[k] for k in required_keys]
        units = {x.unit for x in used_inputs}
        if len(units) > 1:
            return CalculationResult(
                triggered=True,
                refused=True,
                refusal_reason="Calculator refused: cannot combine inputs with mismatched units.",
                rbac_dropped_passages=dropped_count,
            )
        unit = next(iter(units), "")
        if "difference" in lowered or "exceed" in lowered or "above" in lowered or "minus" in lowered:
            formula = " - ".join(str(x.value) for x in used_inputs)
        else:
            formula = " + ".join(str(x.value) for x in used_inputs)
        val = safe_eval_arithmetic(formula)
        formatted = _format_value(val, unit)
        cites = ", ".join(x.chunk_id for x in used_inputs if x.chunk_id)
        return CalculationResult(
            triggered=True,
            refused=False,
            formula=formula,
            inputs=used_inputs,
            result=val,
            unit=unit,
            formatted_result=formatted,
            formatted_summary=f"Verified calculation: {formula} = {formatted} (cited: {cites})",
            rbac_dropped_passages=dropped_count,
        )

    # Case 3: Single percentage operand with explicit arithmetic modifier ("remaining after deficit")
    if len(required_keys) == 1 and ("remaining" in lowered or "after" in lowered) and available[required_keys[0]].unit == "%":
        inp = available[required_keys[0]]
        formula = f"100 - {inp.value}"
        val = safe_eval_arithmetic(formula)
        formatted = _format_value(val, "%")
        return CalculationResult(
            triggered=True,
            refused=False,
            formula=formula,
            inputs=[inp],
            result=val,
            unit="%",
            formatted_result=formatted,
            formatted_summary=f"Verified calculation: {formula} = {formatted} (cited: {inp.chunk_id})",
            rbac_dropped_passages=dropped_count,
        )

    return CalculationResult(
        triggered=True,
        refused=True,
        refusal_reason=(
            "Calculator refused: insufficient operands in role-permitted passages to "
            "perform a complete deterministic calculation."
        ),
        rbac_dropped_passages=dropped_count,
    )


__all__ = [
    "CalculationResult",
    "CalculatorInput",
    "UnsafeExpressionError",
    "run_compliance_calculator",
    "safe_eval_arithmetic",
]
