# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Task contract checker — internal calm ≠ task success.

Wraps the coding-agent contract probe helpers so the control plane can
override finalize when the TASK's own examples/rejects fail.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ContractResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    missing_symbols: List[str] = field(default_factory=list)
    probe_error: str = ""
    source: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def check_task_contract(
    task: str,
    *,
    files_on_disk: Optional[List[str]] = None,
    run_probe: Optional[Callable[[], Dict[str, Any]]] = None,
    required_files: Optional[List[str]] = None,
    required_symbols: Optional[List[str]] = None,
) -> ContractResult:
    """Evaluate whether the delivered artifact satisfies the TASK text.

    Prefer an injected ``run_probe`` (sandbox contract probe). Fall back to
    static path/symbol presence only.
    """
    reasons: List[str] = []
    missing_files: List[str] = []
    missing_symbols: List[str] = []

    try:
        from local_ui.code_agent import (
            _task_target_files, _task_required_symbols,
        )
        req_files = required_files if required_files is not None else _task_target_files(task)
        req_syms = required_symbols if required_symbols is not None else _task_required_symbols(task)
    except Exception:
        req_files = list(required_files or [])
        req_syms = list(required_symbols or [])

    have = set(files_on_disk or [])
    for p in req_files:
        if p not in have:
            missing_files.append(p)
            reasons.append(f"missing file {p}")

    if run_probe is not None:
        try:
            out = run_probe() or {}
            if not out.get("ok"):
                err = (out.get("err") or out.get("error") or "probe failed")[:400]
                reasons.append(f"probe: {err}")
                return ContractResult(
                    ok=False, reasons=reasons, missing_files=missing_files,
                    missing_symbols=missing_symbols, probe_error=err, source="probe",
                )
            if missing_files:
                return ContractResult(
                    ok=False, reasons=reasons, missing_files=missing_files,
                    missing_symbols=missing_symbols, source="probe+paths",
                )
            return ContractResult(ok=True, reasons=[], source="probe")
        except Exception as exc:
            reasons.append(f"probe error: {exc}")
            return ContractResult(
                ok=False, reasons=reasons, missing_files=missing_files,
                probe_error=str(exc)[:200], source="probe_error",
            )

    # Static-only: paths present is weak but better than nothing.
    ok = not missing_files
    if req_syms and not have:
        reasons.append("symbols required but no files on disk")
        ok = False
    return ContractResult(
        ok=ok, reasons=reasons, missing_files=missing_files,
        missing_symbols=missing_symbols, source="static",
    )
