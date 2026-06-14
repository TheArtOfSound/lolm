# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Deterministic verifiers — the arithmetic a language model must not freehand.

The sharpest finding across every audit of this project: the model checked its
notes, chose the right strategy, and *still* wrote "3 weeks x $3,300" when the
figures it had been given multiply to $1,650. A proof layer that streams
beautiful telemetry but lets a wrong number through is the exact "proof ahead of
the proof" failure the critiques named. Encryption, control logits, and
confidence spans do not make a wrong total right.

These checks are pure Python — no model, no torch, no network. They re-derive
the arithmetic stated in an answer and *contradict* it when the claimed result
is wrong, so a receipt can carry ``math_check_failed`` as a first-class negative
verdict instead of flattering a bad figure. Nothing here trusts the model; it
re-computes and compares.

Design rules:
  * No ``eval`` — a tokenizer + a two-pass precedence evaluator. The only inputs
    that ever reach it are numbers and arithmetic operators we extracted
    ourselves.
  * Conservative: only flag a claim we are confident we parsed (two+ numeric
    operands, a real operator, an ``=``, a numeric result). When unsure, stay
    silent — a false "math failed" is itself a dishonest receipt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ── number / operator lexicon ────────────────────────────────────────────────
# "x", "times", "*", "·", "×" all mean multiply in the prose these answers use.
_OP_WORDS = {
    "times": "*", "multiplied by": "*", "x": "*", "×": "*", "·": "*", "*": "*",
    "plus": "+", "+": "+",
    "minus": "-", "−": "-", "-": "-",
    "divided by": "/", "over": "/", "÷": "/", "/": "/",
}
# A number: optional $, digits with thousands commas, optional decimals. We keep
# a trailing % separately so "20% of 50" is handled by the percentage checker.
_NUM = r"\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$?\d+(?:\.\d+)?"
_OP = r"(?:\*|×|·|x|÷|/|\+|−|-|times|multiplied by|divided by|over|plus|minus)"

# A chained arithmetic claim ending in "= <number>". Requires at least two
# operands joined by an operator, then "=", then a numeric result. The operator
# class deliberately excludes a bare "-" between spaces-less tokens handled in
# _looks_like_real_equation to avoid ranges/dates.
_EQUATION_RE = re.compile(
    rf"((?:{_NUM})(?:\s*{_OP}\s*(?:{_NUM}))+)\s*=\s*({_NUM})",
    re.IGNORECASE,
)

# "20% of 50 = 10" / "20% of 50 is 10".
_PERCENT_RE = re.compile(
    rf"(\d+(?:\.\d+)?)\s*%\s*of\s*({_NUM})\s*(?:=|is|equals)\s*({_NUM})",
    re.IGNORECASE,
)

_TOKEN_RE = re.compile(rf"({_NUM}|\*|×|·|x|÷|/|\+|−|-|times|multiplied by|divided by|over|plus|minus)", re.IGNORECASE)

# Prose-tolerant multiply/add chains: numbers joined by SPACED safe operators,
# tolerating unit words the way models actually write — "10 hours/week * 3 weeks
# = 30 hours", "30 hours * $55/hour = $1650". '/', '-', 'over', and 'minus' are
# deliberately EXCLUDED here so a unit rate ("$55/hour") or a year range
# ("2024-2026") is never misread as a division or subtraction.
_ATTACH = r"(?:/[A-Za-z][\w/.\-]*|%)?"            # attached rate/unit: $55/hour, 50%
_UNITS = r"(?:\s+[A-Za-z][A-Za-z%.\-/]*){0,3}"    # spaced word units: 3 weeks, 30 hours
_SAFE = r"(?:\*|×|·|x|times|multiplied\s+by|plus|\+)"
_NUMU = rf"(?:{_NUM}){_ATTACH}{_UNITS}"           # a number plus its units
_PROSE_EQ = re.compile(
    rf"((?:{_NUM})){_ATTACH}{_UNITS}((?:\s+{_SAFE}\s+{_NUMU})+)\s*=\s*((?:{_NUM}))",
    re.IGNORECASE)
_PROSE_PAIR = re.compile(rf"\s+({_SAFE})\s+({_NUM})", re.IGNORECASE)


def _to_number(token: str) -> Optional[float]:
    """Parse '$3,300' / '1,650.50' / '55' → float. None if not a number."""
    t = token.strip().lstrip("$").replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _normalize_op(token: str) -> Optional[str]:
    return _OP_WORDS.get(token.strip().lower())


def _tokenize(expr: str) -> Optional[List[Any]]:
    """Turn '3 x 10 x $55' into [3.0, '*', 10.0, '*', 55.0]. None if it doesn't
    cleanly alternate number/operator/number."""
    raw = _TOKEN_RE.findall(expr)
    if not raw:
        return None
    tokens: List[Any] = []
    expect_number = True
    for piece in raw:
        if expect_number:
            n = _to_number(piece)
            if n is None:
                return None
            tokens.append(n)
        else:
            op = _normalize_op(piece)
            if op is None:
                return None
            tokens.append(op)
        expect_number = not expect_number
    # Must end on a number and contain at least one operator.
    if expect_number or len(tokens) < 3:
        return None
    return tokens


def _evaluate(tokens: List[Any]) -> Optional[float]:
    """Two-pass, left-associative, * and / before + and -. No eval()."""
    # Pass 1: multiplication / division.
    pass1: List[Any] = [tokens[0]]
    i = 1
    while i < len(tokens):
        op, num = tokens[i], tokens[i + 1]
        if op == "*":
            pass1[-1] = pass1[-1] * num
        elif op == "/":
            if num == 0:
                return None
            pass1[-1] = pass1[-1] / num
        else:
            pass1.append(op)
            pass1.append(num)
        i += 2
    # Pass 2: addition / subtraction.
    result = pass1[0]
    i = 1
    while i < len(pass1):
        op, num = pass1[i], pass1[i + 1]
        if op == "+":
            result = result + num
        elif op == "-":
            result = result - num
        i += 2
    return result


def _looks_like_real_equation(lhs: str) -> bool:
    """Filter out version strings, dates, score lines, and variable algebra that
    would produce false 'math failed' verdicts."""
    # Bare hyphen ranges/dates like "2024-2026" or "p-value": require the operator
    # to be surrounded by spaces or be an explicit word/symbol, which the regex
    # already enforces with \s*. Extra guard: reject if any operand is a 4-digit
    # year-only token joined solely by '-' (date range).
    if re.fullmatch(r"\s*\d{4}\s*-\s*\d{4}\s*", lhs):
        return False
    return True


def verify_arithmetic(text: str, rel_tol: float = 0.01, abs_tol: float = 0.5) -> List[Dict[str, Any]]:
    """Find ``a op b [op c ...] = d`` claims and check d against the computed LHS.

    Returns one record per checked claim:
        {"kind": "arithmetic", "claim": "3 x 10 x $55 = $3,300",
         "computed": 1650.0, "claimed": 3300.0, "ok": False}
    Only claims we could fully parse are returned, so an empty list means
    "nothing checkable", never "all correct".
    """
    by_anchor: Dict[int, Dict[str, Any]] = {}  # dedupe bare vs prose by result pos

    def _record(anchor: int, claim_str: str, tokens: Optional[List[Any]],
                claimed: Optional[float]) -> None:
        if tokens is None or claimed is None:
            return
        computed = _evaluate(tokens)
        if computed is None:
            return
        tol = max(abs_tol, abs(computed) * rel_tol)
        by_anchor[anchor] = {
            "kind": "arithmetic",
            "claim": re.sub(r"\s+", " ", claim_str).strip(),
            "computed": round(computed, 4),
            "claimed": round(claimed, 4),
            "ok": abs(computed - claimed) <= tol,
        }

    # Bare equations (also covers / and -): "3 x 10 x $55 = $3,300".
    for m in _EQUATION_RE.finditer(text):
        if not _looks_like_real_equation(m.group(1)):
            continue
        _record(m.end(), m.group(0), _tokenize(m.group(1)), _to_number(m.group(2)))

    # Prose-tolerant ×/+ with unit words: "10 hours/week * 3 weeks = 30 hours".
    for m in _PROSE_EQ.finditer(text):
        first = _to_number(m.group(1))
        if first is None:
            continue
        tokens: List[Any] = [first]
        ok_chain = True
        for pm in _PROSE_PAIR.finditer(m.group(2)):
            op = _normalize_op(pm.group(1))
            n = _to_number(pm.group(2))
            if op is None or n is None:
                ok_chain = False
                break
            tokens += [op, n]
        if ok_chain and len(tokens) >= 3:
            _record(m.end(), m.group(0), tokens, _to_number(m.group(3)))

    return list(by_anchor.values())


def verify_percentages(text: str, rel_tol: float = 0.01, abs_tol: float = 0.5) -> List[Dict[str, Any]]:
    """Check ``N% of M = K`` claims."""
    checks: List[Dict[str, Any]] = []
    for m in _PERCENT_RE.finditer(text):
        pct = _to_number(m.group(1))
        base = _to_number(m.group(2))
        claimed = _to_number(m.group(3))
        if pct is None or base is None or claimed is None:
            continue
        computed = pct / 100.0 * base
        tol = max(abs_tol, abs(computed) * rel_tol)
        checks.append({
            "kind": "percentage",
            "claim": re.sub(r"\s+", " ", m.group(0)).strip(),
            "computed": round(computed, 4),
            "claimed": round(claimed, 4),
            "ok": abs(computed - claimed) <= tol,
        })
    return checks


# Exact time-unit conversions only — months/years are ambiguous (28-31 days,
# 365/366) so we never strict-check them; a false "wrong" is itself dishonest.
_UNIT_HOURS = {"minute": 1.0 / 60.0, "hour": 1.0, "day": 24.0, "week": 168.0}
_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(minutes?|hours?|days?|weeks?)\s*(?:=|==|is|equals|amounts? to)\s*"
    r"(\d+(?:\.\d+)?)\s*(minutes?|hours?|days?|weeks?)\b",
    re.IGNORECASE)


# A duration "N unit = M unit" immediately preceded by an arithmetic operator is
# the TAIL of a calculation ("10 hours/week * 3 weeks = 30 hours" — already
# checked by verify_arithmetic), NOT a claim that the two units are equal.
# Re-reading it as a weeks->hours conversion produces a false "math failed",
# which is itself a dishonest receipt — exactly what these verifiers must avoid.
_ARITH_BEFORE = re.compile(
    r"(?:[*×·+/÷]|\b(?:x|times|plus|minus|multiplied\s+by|divided\s+by))\s*$",
    re.IGNORECASE)


def verify_durations(text: str, rel_tol: float = 0.001) -> List[Dict[str, Any]]:
    """Check stated unit conversions: '3 weeks = 21 days', '2 hours is 120 minutes'."""
    checks: List[Dict[str, Any]] = []
    for m in _DURATION_RE.finditer(text):
        if _ARITH_BEFORE.search(text[:m.start(1)]):
            continue  # tail of an arithmetic chain, not a unit-conversion claim
        lv, lu = _to_number(m.group(1)), m.group(2).rstrip("s").lower()
        rv, ru = _to_number(m.group(3)), m.group(4).rstrip("s").lower()
        if lv is None or rv is None or lu not in _UNIT_HOURS or ru not in _UNIT_HOURS:
            continue
        left_h = lv * _UNIT_HOURS[lu]
        right_h = rv * _UNIT_HOURS[ru]
        tol = max(1e-6, abs(left_h) * rel_tol)
        checks.append({
            "kind": "duration",
            "claim": re.sub(r"\s+", " ", m.group(0)).strip(),
            "computed": round(rv * _UNIT_HOURS[ru] / _UNIT_HOURS[ru], 4),  # right side in its own unit
            "expected": round(left_h / _UNIT_HOURS[ru], 4),               # left side converted to right unit
            "ok": abs(left_h - right_h) <= tol,
        })
    return checks


def run_text_verifiers(text: str) -> Dict[str, Any]:
    """Run every deterministic check over an answer and summarize.

    {
      "checks": [...],          # every claim we re-derived
      "checked": int,           # how many claims were checkable
      "failed": int,            # how many were wrong
      "passed": bool|None,      # None when nothing was checkable
      "labels": ["math_check_failed"] | [],
    }
    """
    checks = (verify_arithmetic(text or "") + verify_percentages(text or "")
              + verify_durations(text or ""))
    failed = [c for c in checks if not c["ok"]]
    if not checks:
        passed: Optional[bool] = None
    else:
        passed = not failed
    return {
        "checks": checks,
        "checked": len(checks),
        "failed": len(failed),
        "passed": passed,
        "labels": ["math_check_failed"] if failed else [],
    }
