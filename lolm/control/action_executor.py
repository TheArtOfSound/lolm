# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Action executor — an NFET decision is not control unless it is consumed.

Every execute() returns ExecutionResult with ``consumed=True`` only when the
generation path or sandbox state actually changed. Logging alone is never
consumed=True.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


# Canonical action set (v1)
ACTIONS = (
    "continue", "deliberate", "retrieve", "branch", "compare", "verify",
    "retry", "compress", "reset", "tool", "stop", "refuse", "finalize",
)


@dataclass
class ExecutionResult:
    action: str
    consumed: bool
    side_effects: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    ms: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutorContext:
    """Minimal bag the coding / dialog loops fill in."""

    task: str = ""
    phase: str = "work"
    exit_ok: bool = False
    contract_ok: bool = True
    thrash: int = 0
    # Callbacks (optional) — when set, executor can invoke real side effects.
    run_contract: Optional[Callable[[], Dict[str, Any]]] = None
    run_verify: Optional[Callable[[], Dict[str, Any]]] = None
    do_retrieve: Optional[Callable[[], List[Dict[str, Any]]]] = None
    do_branch: Optional[Callable[[], Dict[str, Any]]] = None
    authorize_finalize: Optional[Callable[[], bool]] = None
    force_retry: Optional[Callable[[], None]] = None
    notes: List[str] = field(default_factory=list)


class ActionExecutor:
    """Maps abstract actions to side effects; records consumption honestly."""

    def __init__(self) -> None:
        self.history: List[ExecutionResult] = []

    def execute(self, action: str, ctx: ExecutorContext) -> ExecutionResult:
        action = (action or "continue").strip().lower()
        if action not in ACTIONS:
            res = ExecutionResult(action=action, consumed=False,
                                  error=f"unknown action {action!r}")
            self.history.append(res)
            return res

        handlers = {
            "continue": self._continue,
            "deliberate": self._deliberate,
            "retrieve": self._retrieve,
            "branch": self._branch,
            "compare": self._compare,
            "verify": self._verify,
            "retry": self._retry,
            "compress": self._compress,
            "reset": self._reset,
            "tool": self._tool,
            "stop": self._stop,
            "refuse": self._refuse,
            "finalize": self._finalize,
        }
        res = handlers[action](ctx)
        self.history.append(res)
        return res

    def _continue(self, ctx: ExecutorContext) -> ExecutionResult:
        # Continue is always "consumed" as the default generation path.
        return ExecutionResult("continue", True, side_effects=["proceed"])

    def _deliberate(self, ctx: ExecutorContext) -> ExecutionResult:
        # v1: deliberate ≡ force an extra contract/verify pass if available.
        if ctx.run_contract is not None:
            out = ctx.run_contract() or {}
            return ExecutionResult(
                "deliberate", True,
                side_effects=["contract_probe"],
                evidence=[out],
                meta={"contract_ok": bool(out.get("ok"))},
            )
        if ctx.run_verify is not None:
            out = ctx.run_verify() or {}
            return ExecutionResult(
                "deliberate", True, side_effects=["verify"], evidence=[out],
            )
        return ExecutionResult(
            "deliberate", False,
            error="no deliberate hook — would only log",
        )

    def _retrieve(self, ctx: ExecutorContext) -> ExecutionResult:
        if ctx.do_retrieve is None:
            return ExecutionResult("retrieve", False, error="no retrieve hook")
        hits = ctx.do_retrieve() or []
        return ExecutionResult(
            "retrieve", True,
            side_effects=[f"memory_hits={len(hits)}"],
            evidence=list(hits)[:12],
        )

    def _branch(self, ctx: ExecutorContext) -> ExecutionResult:
        if ctx.do_branch is None:
            return ExecutionResult("branch", False, error="no branch hook")
        out = ctx.do_branch() or {}
        return ExecutionResult(
            "branch", True,
            side_effects=["ensemble_or_fork"],
            evidence=[out],
            meta=out,
        )

    def _compare(self, ctx: ExecutorContext) -> ExecutionResult:
        # v1 compare uses contract as scoring oracle.
        if ctx.run_contract is None:
            return ExecutionResult("compare", False, error="no contract for compare")
        out = ctx.run_contract() or {}
        return ExecutionResult(
            "compare", True, side_effects=["scored_via_contract"], evidence=[out],
        )

    def _verify(self, ctx: ExecutorContext) -> ExecutionResult:
        effects = []
        evidence = []
        if ctx.run_verify is not None:
            evidence.append(ctx.run_verify() or {})
            effects.append("verify")
        if ctx.run_contract is not None:
            evidence.append(ctx.run_contract() or {})
            effects.append("contract")
        if not effects:
            return ExecutionResult("verify", False, error="no verify/contract hook")
        return ExecutionResult("verify", True, side_effects=effects, evidence=evidence)

    def _retry(self, ctx: ExecutorContext) -> ExecutionResult:
        if ctx.force_retry is None:
            return ExecutionResult("retry", False, error="no retry hook")
        ctx.force_retry()
        return ExecutionResult("retry", True, side_effects=["discard_last_attempt"])

    def _compress(self, ctx: ExecutorContext) -> ExecutionResult:
        # Session-scale; v1 records intent only if no hook.
        return ExecutionResult(
            "compress", False,
            error="compress not wired at this timescale yet",
        )

    def _reset(self, ctx: ExecutorContext) -> ExecutionResult:
        if ctx.force_retry is not None:
            ctx.force_retry()
            return ExecutionResult("reset", True, side_effects=["clear_thrash_authorize_rewrite"])
        return ExecutionResult("reset", False, error="no reset hook")

    def _tool(self, ctx: ExecutorContext) -> ExecutionResult:
        if ctx.run_verify is not None:
            # Sandbox run is the coding "tool".
            out = ctx.run_verify() or {}
            return ExecutionResult("tool", True, side_effects=["sandbox_run"], evidence=[out])
        return ExecutionResult("tool", False, error="no tool hook")

    def _stop(self, ctx: ExecutorContext) -> ExecutionResult:
        return ExecutionResult("stop", True, side_effects=["halt_generation"])

    def _refuse(self, ctx: ExecutorContext) -> ExecutionResult:
        return ExecutionResult("refuse", True, side_effects=["refuse_finalize"])

    def _finalize(self, ctx: ExecutorContext) -> ExecutionResult:
        if ctx.authorize_finalize is not None:
            ok = bool(ctx.authorize_finalize())
            return ExecutionResult(
                "finalize", ok,
                side_effects=["finalize_authorized" if ok else "finalize_blocked"],
                error="" if ok else "contract or controller blocked finalize",
            )
        if not ctx.exit_ok or not ctx.contract_ok:
            return ExecutionResult(
                "finalize", False,
                error="exit or contract not ok",
            )
        return ExecutionResult("finalize", True, side_effects=["finalize_allowed"])
