# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Per-run reliability state bundle used by CodeAgent.

Owns: contract, capability graph, artifacts, arbiter inputs, failure ledger,
branch portfolio, checkpoints, closure, progress budget, confidence, session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lolm.reliability.arbiter import ControllerVote, select_action, ArbiterDecision
from lolm.reliability.artifact_state import ArtifactRegistry
from lolm.reliability.branch_portfolio import BranchPortfolio, StrategyVector
from lolm.reliability.capability_graph import CapabilityGraph, environment_fingerprint
from lolm.reliability.checkpoint_store import CheckpointStore
from lolm.reliability.closure import ClosureProtocol, evaluate_closure
from lolm.reliability.confidence import ConfidenceBundle, from_nfet_and_contract, action_certainty_label
from lolm.reliability.contract_compiler import (
    CompiledContract,
    compile_contract,
    check_manifest_against_contract,
)
from lolm.reliability.failure_ledger import SemanticFailureLedger
from lolm.reliability.progress_budget import EvidenceProgressBudget, ActionDelta
from lolm.reliability.retrieval_bankruptcy import RetrievalBankruptcy
from lolm.reliability.runtime_manifest import RuntimeManifest, build_runtime_manifest
from lolm.reliability.session_ledger import SessionIntentLedger


_DESKTOP_OPEN = re.compile(r"^\s*(xdg-open|open)\b", re.I)


@dataclass
class RunReliabilityState:
    task: str
    contract: CompiledContract
    capabilities: CapabilityGraph
    artifacts: ArtifactRegistry = field(default_factory=ArtifactRegistry)
    failures: SemanticFailureLedger = field(default_factory=SemanticFailureLedger)
    branches: BranchPortfolio = field(default_factory=BranchPortfolio)
    checkpoints: CheckpointStore = field(default_factory=CheckpointStore)
    closure: ClosureProtocol = field(default_factory=ClosureProtocol)
    budget: Optional[EvidenceProgressBudget] = None
    retrieval: RetrievalBankruptcy = field(default_factory=RetrievalBankruptcy)
    session: Optional[SessionIntentLedger] = None
    manifest: Optional[RuntimeManifest] = None
    last_decision: Optional[ArbiterDecision] = None
    confidence: Optional[ConfidenceBundle] = None
    current_strategy: StrategyVector = field(default_factory=StrategyVector)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    closed_early: bool = False

    @classmethod
    def open(
        cls,
        task: str,
        *,
        max_steps: int = 18,
        session_id: str = "",
        conversation_id: str = "",
        owner: str = "",
        reasoner_profile: str = "",
        active_model: str = "",
        graft_state: str = "synthetic",
    ) -> "RunReliabilityState":
        caps = CapabilityGraph()
        contract = compile_contract(task, environment_caps=caps.available_set())
        env = caps.fingerprint
        failures = SemanticFailureLedger(environment_id=env)
        # Seed strategy from contract primary language
        strategy = StrategyVector(
            artifact_schema={
                "html": "single_html",
                "pdf": "pdf_report",
                "python": "python_module",
            }.get(contract.primary_language, "unknown"),
            implementation_pattern="",
            dependency_plan="stdlib_only",
            tool_plan="sandbox_run",
            verifier_plan={
                "html": "html.render",
                "pdf": "pdf.exists",
                "python": "syntax.python",
            }.get(contract.primary_language, "exists.path"),
            label="initial",
        )
        session = None
        if session_id or conversation_id:
            try:
                session = SessionIntentLedger(
                    session_id=session_id or conversation_id,
                    owner=owner,
                    conversation_id=conversation_id,
                )
            except Exception:
                session = None
        manifest = build_runtime_manifest(
            reasoner_profile=reasoner_profile,
            active_model=active_model,
            graft_state=graft_state,
            capabilities=list(caps.available_set()),
            browser_verifier="html.render" if caps.is_available("html.render") else "static_lint",
            network_enabled=bool(caps.is_available("network.outbound")),
        )
        return cls(
            task=task,
            contract=contract,
            capabilities=caps,
            failures=failures,
            budget=EvidenceProgressBudget(max_steps=max_steps),
            session=session,
            manifest=manifest,
            current_strategy=strategy,
        )

    def note_write(self, path: str, content: str, *, step: int = 0) -> None:
        role = "deliverable"
        if path not in self.contract.required_paths and self.contract.exact_count == 1:
            role = "helper"
        validators = []
        lang_hint = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if lang_hint == "py":
            validators = ["syntax.python"]
        elif lang_hint in ("html", "htm"):
            validators = ["html.static_lint", "html.render"]
        elif lang_hint == "pdf":
            validators = ["pdf.exists"]
        self.artifacts.upsert(
            path, content, step=step, role=role, validators_required=validators,
        )

    def observe_run(
        self,
        command: str,
        *,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        step: int = 0,
    ) -> Dict[str, Any]:
        """Record capability facts + semantic failures for a RUN."""
        notes: Dict[str, Any] = {}
        fact = self.capabilities.observe_command_result(
            command, exit_code=exit_code, stdout=stdout, stderr=stderr,
        )
        if fact is not None:
            notes["capability_fact"] = fact.to_dict()

        # Block desktop open after definitive negative
        if _DESKTOP_OPEN.match(command or ""):
            allowed, why = self.capabilities.may_attempt("desktop.open")
            notes["desktop_open_allowed"] = allowed
            notes["desktop_open_reason"] = why
            if not allowed:
                notes["blocked"] = True
                return notes

        if exit_code != 0:
            art_type = self.contract.primary_language or "unknown"
            fp = self.failures.record(
                command=command,
                stderr=stderr,
                stdout=stdout,
                exit_code=exit_code,
                tool_id=(command or "").split()[0] if command else "",
                artifact_type=art_type,
                strategy_family=self.current_strategy.fingerprint(),
            )
            notes["failure"] = fp.to_dict()
        return notes

    def may_run_command(self, command: str) -> Tuple[bool, str, Optional[str]]:
        """Gate commands against negative capability facts.

        Returns (allowed, reason, alternative_verifier).
        """
        if _DESKTOP_OPEN.match(command or ""):
            allowed, why = self.capabilities.may_attempt("desktop.open")
            if not allowed:
                alts = []
                f = self.capabilities.facts.get("desktop.open")
                if f:
                    alts = list(f.alternatives)
                alt = alts[0] if alts else "html.render"
                return False, why, alt
        return True, "ok", None

    def snapshot_if_green(
        self,
        file_contents: Dict[str, str],
        *,
        step: int,
        compile_ok: bool,
        run_ok: bool = False,
        verifier_outputs: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        if not compile_ok and not run_ok:
            return None
        # Update contract status lightly
        check = check_manifest_against_contract(
            self.contract, list(file_contents.keys()),
            path_hashes={
                p: __import__("hashlib").sha256(c.encode()).hexdigest()
                for p, c in file_contents.items()
            },
        )
        cov = 0.0
        hard = max(len(self.contract.hard_clauses()), 1)
        # Count green deliverables
        green = sum(1 for c in self.contract.hard_clauses() if c.status == "green")
        if run_ok:
            green = max(green, 1)
        cov = green / hard
        return self.checkpoints.force_green(
            file_contents=file_contents,
            contract_coverage=cov,
            green_hard=green,
            open_hard=max(0, hard - green),
            verifier_outputs=verifier_outputs or {"compile": {"ok": compile_ok}, "run": {"ok": run_ok}},
            environment_fingerprint=self.capabilities.fingerprint,
            step=step,
            meta={"check": check},
        )

    def maybe_rollback_on_regression(
        self,
        sandbox: Any,
        *,
        compile_ok: bool,
        current_hashes: Dict[str, str],
    ) -> Optional[Any]:
        regressed, ckpt = self.checkpoints.has_regressed(
            current_hashes, compile_ok=compile_ok,
        )
        if not regressed or ckpt is None:
            return None
        restored = self.checkpoints.materialize_to_sandbox(sandbox, ckpt.checkpoint_id)
        return restored

    def evaluate_and_maybe_close(
        self,
        paths: Sequence[str],
        *,
        path_hashes: Optional[Dict[str, str]] = None,
        validators_green: bool = False,
        step: int = 0,
        checkpoint_id: str = "",
    ) -> Dict[str, Any]:
        check = check_manifest_against_contract(
            self.contract, paths, path_hashes=path_hashes,
        )
        # PDF / exact deliverable special case: existence of required paths + green validators
        open_hard = int(check.get("open_hard") or self.contract.open_hard)
        # If validators green and required present, treat open hard deliverables as closable
        if validators_green and check.get("ok"):
            for c in self.contract.hard_clauses():
                if c.clause_type in ("deliverable", "evidence", "exact_output_set") and c.status != "red":
                    c.status = "green"
            self.contract.recompute_counts()
            open_hard = self.contract.open_hard
            check = check_manifest_against_contract(
                self.contract, paths, path_hashes=path_hashes,
            )

        # Soft main.py should not block HTML/PDF closure
        if self.contract.primary_language in ("html", "pdf"):
            for c in self.contract.clauses:
                if c.hardness == "soft" and c.status == "open":
                    c.status = "waived"
            self.contract.recompute_counts()
            open_hard = self.contract.open_hard

        evaluation = evaluate_closure(
            contract_ok=bool(check.get("ok")) and not self.contract.contradictory,
            exact_manifest_ok=(
                self.contract.exact_count is None
                or check.get("ok")
            ),
            validators_green=validators_green,
            open_hard=open_hard if validators_green else max(open_hard, 1),
            contradictory=self.contract.contradictory,
            deliverable_paths=paths,
            path_hashes=path_hashes,
        )
        # For PDF: if output.pdf exists and generator exited 0, force validators_green path
        if (
            self.contract.primary_language == "pdf"
            and any(p.endswith(".pdf") for p in paths)
            and validators_green
        ):
            evaluation = evaluate_closure(
                contract_ok=True,
                exact_manifest_ok=True,
                validators_green=True,
                open_hard=0,
                contradictory=False,
                deliverable_paths=paths,
                path_hashes=path_hashes,
            )

        result = self.closure.try_close(
            evaluation, checkpoint_id=checkpoint_id, step=step,
        )
        if result.closed:
            self.closed_early = True
            self.artifacts.mark_delivered(list(paths))
        return {"closure": result.to_dict(), "manifest_check": check}

    def arbitrate(
        self,
        *,
        nfet_label: str = "",
        nfet_p: float = 0.0,
        task_state_action: str = "",
        verification_debt: Any = None,
        blocked_capability: str = "",
        blocked_reason: str = "",
        capability_alternatives: Optional[List[str]] = None,
        force_close: bool = False,
    ) -> ArbiterDecision:
        votes: List[ControllerVote] = []
        if nfet_label:
            votes.append(ControllerVote(
                source="nfet",
                action=nfet_label,
                weight=float(nfet_p or 0.5),
                reason="nfet coding head",
                soft=True,
            ))
        if task_state_action:
            votes.append(ControllerVote(
                source="task_state",
                action=task_state_action,
                weight=1.0,
                reason="task-state policy",
                soft=False,  # hard vote
            ))

        hard_missing = []
        substitutes = {}
        verifiers = [c.capability_dependency for c in self.contract.clauses if c.capability_dependency]
        if verifiers:
            resolved = self.capabilities.resolve(verifiers)
            hard_missing = resolved.get("hard_missing") or []
            substitutes = resolved.get("substitutes") or {}

        regressed = False
        last_green_id = None
        best = self.checkpoints.best()
        if best:
            last_green_id = best.checkpoint_id

        req_change = self.failures.requires_causal_change()
        state = {
            "contract_contradictory": self.contract.contradictory,
            "contradictions": list(self.contract.contradictions),
            "hard_missing": hard_missing,
            "substitutes": substitutes,
            "regressed_from_green": regressed,
            "last_green_id": last_green_id,
            "closure_ready": force_close or self.closure.closed or (
                self.closure.result.ready if self.closure.result else False
            ),
            "failure_repeated": self.failures.is_repeated(2),
            "causal_change_proposed": False,
            "required_causal_change": req_change,
            "root_cause": (
                self.failures.current_root_cause().normalized_root_cause
                if self.failures.current_root_cause() else None
            ),
            "verification_debt": verification_debt,
            "retrieval_positive_gain": False,
            "blocked_capability": blocked_capability,
            "blocked_capability_reason": blocked_reason,
            "capability_alternatives": capability_alternatives or [],
            "capability_infeasible": bool(
                blocked_capability or self.failures.current_root_cause()
                and (self.failures.current_root_cause().normalized_root_cause or "").startswith(
                    "capability_missing"
                )
            ),
            "nonpositive_deltas": self.budget.nonpositive_streak if self.budget else 0,
            "max_nonpositive": self.budget.max_nonpositive if self.budget else 3,
            "budget_frozen": self.budget.frozen if self.budget else False,
        }
        decision = select_action(state, votes)
        self.last_decision = decision
        self.decisions.append(decision.to_dict())

        # Confidence bundle
        hard = self.contract.hard_clauses()
        green = sum(1 for c in hard if c.status == "green")
        self.confidence = from_nfet_and_contract(
            nfet_label=nfet_label,
            nfet_p=nfet_p,
            green_hard=green,
            total_hard=len(hard),
            validators_run=sum(len(r.validators_run) for r in self.artifacts.records.values()),
            validators_required=max(1, sum(len(r.validators_required) for r in self.artifacts.records.values())),
            capability_ok=not hard_missing and not blocked_capability,
            artifact_evidence_ok=green > 0 and not self.failures.is_repeated(3),
        )
        return decision

    def record_delta(
        self,
        step: int,
        action: str,
        *,
        coverage_before: float,
        coverage_after: float,
        info_gain: float = 0.0,
        error_novelty: float = 0.0,
    ) -> None:
        if self.budget is None:
            return
        self.budget.record(ActionDelta(
            step=step,
            action=action,
            contract_coverage_delta=coverage_after - coverage_before,
            information_gain=info_gain,
            error_novelty=error_novelty,
        ))

    def receipt_blob(self) -> Dict[str, Any]:
        return {
            "schema": "lolm.reliability.run.v1",
            "contract": self.contract.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "artifacts": self.artifacts.to_dict(),
            "failures": self.failures.to_dict(),
            "branches": self.branches.to_dict(),
            "checkpoints": self.checkpoints.to_dict(),
            "closure": self.closure.to_dict(),
            "budget": self.budget.to_dict() if self.budget else None,
            "retrieval": self.retrieval.to_dict(),
            "confidence": self.confidence.ui_fields() if self.confidence else None,
            "last_decision": self.last_decision.to_dict() if self.last_decision else None,
            "decisions": self.decisions[-30:],
            "runtime_manifest": self.manifest.to_dict() if self.manifest else None,
            "strategy": self.current_strategy.to_dict(),
            "closed_early": self.closed_early,
        }

    def system_prompt_addon(self) -> str:
        """Extra system context from contract + capabilities (not band-aid)."""
        lines = [
            "── RELIABILITY CONTRACT (binding) ──",
            f"contract_id: {self.contract.contract_id}",
            f"primary_language: {self.contract.primary_language}",
            f"feasibility: {self.contract.feasibility}",
        ]
        if self.contract.required_paths:
            lines.append("required_paths: " + ", ".join(self.contract.required_paths))
        if self.contract.exact_count is not None:
            lines.append(f"exact_deliverable_count: {self.contract.exact_count}")
        if self.contract.forbidden_extensions:
            lines.append("forbidden_extensions: " + ", ".join(self.contract.forbidden_extensions))
        if self.contract.contradictory:
            lines.append("CONTRADICTORY CONTRACT — do not mutate artifacts; clarify.")
            for c in self.contract.contradictions[:3]:
                lines.append(f"  ! {c}")
        # Capability negatives
        for cid, fact in self.capabilities.facts.items():
            if not fact.available and fact.strength == "definitive":
                lines.append(
                    f"CAPABILITY UNAVAILABLE: {cid} — {fact.evidence[:100]}; "
                    f"use alternatives: {', '.join(fact.alternatives) or 'none'}"
                )
        if self.contract.primary_language == "html":
            lines.append(
                "HTML tasks: verify via html.render / static lint — NEVER xdg-open."
            )
        if self.contract.primary_language != "python":
            lines.append(
                f"Do NOT default to main.py; primary artifact type is "
                f"{self.contract.primary_language}."
            )
        return "\n".join(lines)
