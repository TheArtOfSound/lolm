# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Reconcile compiled completion clauses with the selected artifact medium.

A word such as ``browser`` may appear inside requested document content, test labels,
or filenames. That lexical occurrence must not add a hard ``html.render`` criterion to
a PDF, Python, or other non-HTML task. The compiler's selected primary medium remains
authoritative; this patch removes only the incompatible browser-render behavior clause.
"""
from __future__ import annotations

from typing import Any, Callable


def install_patch() -> None:
    """Install the medium-reconciliation wrapper once."""
    from lolm.reliability import contract_compiler as compiler

    current: Callable[..., Any] = compiler.compile_contract
    if getattr(current, "_lolm_medium_reconciled", False):
        return

    original = current

    def compile_contract(user_request: str, *, environment_caps=None):
        contract = original(user_request, environment_caps=environment_caps)
        if contract.primary_language != "html":
            contract.clauses = [
                clause
                for clause in contract.clauses
                if not (
                    clause.clause_type == "behavior"
                    and clause.verifier == "html.render"
                )
            ]
            contract.recompute_counts()
        return contract

    compile_contract._lolm_medium_reconciled = True  # type: ignore[attr-defined]
    compile_contract._lolm_original = original  # type: ignore[attr-defined]
    compiler.compile_contract = compile_contract

    # ``run_state`` may already be imported in tests or embedded runtimes. Replace its
    # local function binding as well; normal production startup imports it afterward.
    try:
        from lolm.reliability import run_state

        run_state.compile_contract = compile_contract
    except Exception:
        pass
