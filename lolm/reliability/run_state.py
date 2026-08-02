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
from lolm.reliability.evidence import (
    coerce_exit_code,
    hash_tree,
    html_verdict_ok,
    is_trivial_command,
    meaningful_run_evidence,
    normalize_verifier_output,
    pdf_bytes_valid,
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
        exit_code: Any = None,
        result: Optional[Dict[str, Any]] = None,
        stdout: str = "",
        stderr: str = "",
        step: int = 0,
    ) -> Dict[str, Any]:
        """Record capability facts + semantic failures for a RUN.

        Prefer ``result`` dict so exit code 0 is preserved (never ``x or 1``).
        """
        if result is not None:
            exit_code = coerce_exit_code(result)
            stdout = stdout or (result.get("stdout") or "")
            stderr = stderr or (result.get("stderr") or "")
        else:
            try:
                exit_code = int(exit_code) if exit_code is not None else 1
            except (TypeError, ValueError):
                exit_code = 1

        notes: Dict[str, Any] = {"exit_code": exit_code}
        fact = self.capabilities.observe_command_result(
            command, exit_code=exit_code, stdout=stdout, stderr=stderr,
        )
        if fact is not None:
            notes["capability_fact"] = fact.to_dict()

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
        compile_ok: bool = False,
        run_ok: bool = False,
        run_command: str = "",
        verifier_outputs: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Checkpoint only with artifact-appropriate meaningful verifiers."""
        vos = dict(verifier_outputs or {})
        # Annotate trivial runs so LGTS rejects cat-as-green
        if run_ok and run_command:
            trivial = is_trivial_command(run_command)
            vos.setdefault("run", {
                "ok": run_ok and not trivial and meaningful_run_evidence(run_command, 0),
                "cmd": run_command[:120],
                "trivial": trivial,
            })
        if compile_ok:
            vos.setdefault("syntax.python", {"ok": True})

        independent_hashes = hash_tree(file_contents)
        check = check_manifest_against_contract(
            self.contract, list(file_contents.keys()),
            path_hashes=independent_hashes,
        )
        hard = max(len(self.contract.hard_clauses()), 1)
        green = sum(1 for c in self.contract.hard_clauses() if c.status == "green")
        cov = green / hard
        return self.checkpoints.force_green(
            file_contents=file_contents,
            contract_coverage=cov,
            green_hard=green,
            open_hard=max(0, hard - green),
            verifier_outputs=vos,
            environment_fingerprint=self.capabilities.fingerprint,
            step=step,
            meta={"check": check, "independent_hashes": independent_hashes},
            primary_language=self.contract.primary_language,
            compile_ok=compile_ok,
            run_ok=run_ok,
            run_command=run_command,
            require_meaningful=True,
        )

    def maybe_rollback_on_regression(
        self,
        sandbox: Any,
        *,
        compile_ok: Optional[bool] = None,
        current_hashes: Optional[Dict[str, str]] = None,
        file_contents: Optional[Dict[str, str]] = None,
        verifier_outputs: Optional[Dict[str, Any]] = None,
        contract_coverage: Optional[float] = None,
    ) -> Optional[Any]:
        contents = dict(file_contents or {})
        hashes = current_hashes or (hash_tree(contents) if contents else {})
        check = check_manifest_against_contract(
            self.contract, list(hashes.keys()), path_hashes=hashes,
        )
        regressed, ckpt, why = self.checkpoints.has_regressed(
            hashes,
            compile_ok=compile_ok,
            contract_coverage=(
                contract_coverage if contract_coverage is not None
                else (1.0 - (check.get("open_hard") or 0) / max(len(self.contract.hard_clauses()), 1))
            ),
            verifier_outputs=verifier_outputs,
            open_hard=check.get("open_hard"),
            green_hard=check.get("green_hard"),
            extra_files=list(hashes.keys()),
            exact_count=self.contract.exact_count,
        )
        if not regressed or ckpt is None:
            return None
        restored = self.checkpoints.materialize_to_sandbox(
            sandbox, ckpt.checkpoint_id, current_paths=list(hashes.keys()),
        )
        if restored is not None:
            restored.meta = dict(restored.meta or {}, rollback_reason=why)
        return restored

    def evaluate_and_maybe_close(
        self,
        paths: Sequence[str],
        *,
        file_contents: Optional[Dict[str, Any]] = None,
        claimed_hashes: Optional[Dict[str, str]] = None,
        validators_green: bool = False,
        verifier_outputs: Optional[Dict[str, Any]] = None,
        step: int = 0,
        checkpoint_id: str = "",
    ) -> Dict[str, Any]:
        """Close only with independent content hashes — no language-specific force.

        PDF force-override removed (audit ban on task-specific bandages).
        """
        contents = dict(file_contents or {})
        # Authoritative hashes from bytes only
        independent = hash_tree(contents) if contents else {}
        check = check_manifest_against_contract(
            self.contract, list(paths or contents.keys()),
            path_hashes=independent,
        )

        # Soft main.py waiver only (never force hard clauses green)
        if self.contract.primary_language in ("html", "pdf"):
            for c in self.contract.clauses:
                if c.hardness == "soft" and c.status == "open":
                    c.status = "waived"
            self.contract.recompute_counts()

        # Update deliverable clause status only when the path is present (not "all green")
        for c in self.contract.hard_clauses():
            if c.clause_type == "deliverable" and c.artifact_dependency:
                if c.artifact_dependency in contents and independent.get(c.artifact_dependency):
                    c.status = "green"
                    c.evidence = f"present sha={independent[c.artifact_dependency][:12]}"
                else:
                    c.status = "red"
                    c.evidence = "missing"
            if c.clause_type == "exact_output_set":
                n = len([p for p in contents if p and not p.startswith(".")])
                if self.contract.exact_count is not None and n == self.contract.exact_count:
                    c.status = "green"
                elif self.contract.exact_count is not None:
                    c.status = "red"
                    c.evidence = f"got {n}"
            if c.clause_type == "evidence" and "pdf" in (c.verifier or c.text or "").lower():
                pdfs = [p for p in contents if (p or "").endswith(".pdf")]
                if pdfs and all(pdf_bytes_valid(contents[p]) for p in pdfs):
                    c.status = "green"
                else:
                    c.status = "red"
            if c.clause_type == "behavior" and c.verifier in ("html.render", "html.static_lint"):
                v = (verifier_outputs or {}).get(c.verifier) or (verifier_outputs or {}).get("html.render")
                if isinstance(v, dict) and v.get("ok") is True:
                    c.status = "green"
                else:
                    # leave open unless we have evidence
                    if c.status != "green":
                        c.status = "open"
        self.contract.recompute_counts()
        check = check_manifest_against_contract(
            self.contract, list(paths or contents.keys()),
            path_hashes=independent,
        )

        vos = verifier_outputs or {}
        typed_green = False
        lang = self.contract.primary_language
        if lang == "html":
            for k in ("html.render", "html.static_lint", "browser"):
                v = vos.get(k)
                if isinstance(v, dict) and v.get("ok") is True:
                    typed_green = True
                    break
        elif lang == "pdf":
            v = vos.get("pdf.exists") or vos.get("pdf.validate")
            typed_green = bool(
                isinstance(v, dict) and v.get("ok") and v.get("valid_magic")
            )
            for p in paths or contents.keys():
                if (p or "").endswith(".pdf") and p in contents:
                    if not pdf_bytes_valid(contents[p]):
                        typed_green = False
        else:
            # Python: do NOT auto-close on bare run green — require open_hard == 0
            # from real clause status (symbols/paths already green).
            typed_green = self.contract.open_hard == 0 and bool(check.get("ok"))

        validators_ok = bool(validators_green) and typed_green
        open_hard = int(self.contract.open_hard)

        # Refuse closure while hard criteria remain open
        if open_hard > 0:
            validators_ok = False

        evaluation = evaluate_closure(
            file_contents=contents,
            contract_ok=bool(check.get("ok")) and not self.contract.contradictory,
            exact_manifest_ok=(
                self.contract.exact_count is None or bool(check.get("ok"))
            ),
            validators_green=validators_ok,
            open_hard=open_hard,
            contradictory=self.contract.contradictory,
            deliverable_paths=list(paths or contents.keys()),
            claimed_hashes=claimed_hashes,
            primary_language=self.contract.primary_language,
        )
        result = self.closure.try_close(
            evaluation, checkpoint_id=checkpoint_id, step=step,
        )
        if result.closed:
            self.closed_early = True
            self.artifacts.mark_delivered(list(paths or contents.keys()))
        return {
            "closure": result.to_dict(),
            "manifest_check": check,
            "independent_hashes": independent,
            "validators_ok": validators_ok,
        }

    def apply_resume_package(self, package: Dict[str, Any], sandbox: Any) -> Dict[str, Any]:
        """Restore workspace + reliability state as a typed recovery transaction.

        Recovery privileges do not grant ordinary edit authorization.
        """
        from lolm.privileged_mutation import (
            MutationTrustClass,
            build_recovery_transaction,
            read_sandbox_tree,
            tree_manifest,
        )
        notes: Dict[str, Any] = {"restored_files": [], "grants_edit_authorization": False}
        before = read_sandbox_tree(sandbox)
        pre_hash = tree_manifest(before)["tree_hash"]
        ws = (package or {}).get("workspace_snapshot") or {}
        for path, content in ws.items():
            try:
                sandbox.write_file(path, content, reason="resume_checkpoint")
                notes["restored_files"].append(path)
                self.note_write(path, content if isinstance(content, str) else str(content))
            except Exception as exc:
                notes.setdefault("errors", []).append(f"{path}: {exc}")
        after = read_sandbox_tree(sandbox)
        ckpt_id = str(
            ((package or {}).get("checkpoint_payload") or {}).get("checkpoint_id")
            or (package or {}).get("resume_id")
            or "resume"
        )
        tx = build_recovery_transaction(
            sandbox,
            checkpoint_id=ckpt_id,
            expected_pre_tree_hash=pre_hash,
            before_files=before,
            after_files=after,
            trust_class=MutationTrustClass.RECOVERY_RESUME,
        )
        notes["recovery_transaction"] = tx.to_dict()
        ckpt = (package or {}).get("checkpoint_payload") or {}
        if ckpt.get("file_contents"):
            try:
                self.checkpoints.force_green(
                    file_contents=dict(ckpt["file_contents"]),
                    contract_coverage=float(ckpt.get("contract_coverage") or 0),
                    green_hard=int(ckpt.get("green_hard") or 0),
                    open_hard=int(ckpt.get("open_hard") or 0),
                    verifier_outputs=dict(ckpt.get("verifier_outputs") or {}),
                    step=int(ckpt.get("step") or 0),
                    primary_language=self.contract.primary_language,
                    require_meaningful=False,  # already verified when saved
                    meta={"resumed": True, "checkpoint_id": ckpt.get("checkpoint_id")},
                )
                # Mark as meaningful if payload says so
                best = self.checkpoints.best()
                if best and ckpt.get("verified_meaningful"):
                    best.verified_meaningful = True
            except Exception as exc:
                notes.setdefault("errors", []).append(f"checkpoint: {exc}")
        fl = (package or {}).get("failure_ledger")
        if fl:
            try:
                self.failures = SemanticFailureLedger.from_dict(fl)
            except Exception:
                pass
        notes["resume_token"] = (package or {}).get("resume_token")
        notes["checkpoint_id"] = (package or {}).get("checkpoint_id")
        return notes

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
