# Copyright (c) 2026 Qira LLC. All rights reserved.
"""NFET control specialized for the *coding* agent — the massive missing link.

What NFET is (for coding):
  LOLM's five-stream graft (surface · latent SSM · regime · gate · memory)
  measures per-token dynamics of whatever text it re-reads. The NFET control
  policy turns those measurements into five actions:

      continue  — trajectory healthy, keep going
      retrieve  — sustained uncertainty → gather evidence
      verify    — representation jumped while unsure → check the draft
      branch    — regime collapsed into a rut → try a different approach
      finalize  — calm + confident → ship

What was broken:
  Chat used this. Coding mostly did not. The coding agent was a strong
  write→run→fix harness with multi-model race, but its *control* decisions
  (when to re-test, when to re-race, when to ship) were heuristics and model
  whim. That is the opposite of LOLM's thesis.

What this module does for coding (massively useful):
  1. Re-reads produced source through the graft (when loaded) for real
     entropy/drift/gate/regime — or synthesizes honest proxies from the
     sandbox loop when the graft is offline (prod cascade-only hosts).
  2. Maps control decisions to coding actions:
       retrieve → inject past sealed code receipts + force READ
       verify   → force contract probe / py_compile / self-test focus
       branch   → demand a repair ensemble re-race
       finalize → only allow DONE when contract is green
  3. Surfaces low-confidence *code spans* so the model is told exactly which
     functions measured hot (the thing no plain coding agent can do).
  4. Records a control timeline into the code receipt so every run is
     auditable: not just what ran, but what NFET decided and why.

This is pure optional: if nothing is loaded, synthetic frames still drive
useful control. The loop never hard-depends on torch.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from lolm.nfet_policy import (
    CONTROL_BRANCH,
    CONTROL_CONTINUE,
    CONTROL_FINALIZE,
    CONTROL_RETRIEVE,
    CONTROL_VERIFY,
    CONTROL_LABELS,
    ControlDecision,
    NFETControlPolicy,
    PolicyConfig,
    TelemetryFrame,
)


# Coding-tuned policy: fewer frames of warmup (each "frame" is a whole
# write/run checkpoint, not a token), faster finalize eligibility.
_CODE_POLICY = PolicyConfig(
    window=48,
    min_calibration=3,
    sustain=2,
    cooldown=2,
    entropy_spike_z=1.0,
    drift_spike_z=1.4,
    verify_entropy_z=0.15,
    regime_stall_z=-1.0,
    branch_entropy_z=-0.4,
    finalize_entropy_z=-0.85,
    finalize_drift_z=0.15,
    min_steps_before_finalize=4,
    head_confidence=0.55,
    use_trained_head=True,
)


@dataclass
class CodingControl:
    """One NFET decision translated into coding-agent actions."""

    decision: ControlDecision
    mode: str = "synthetic"          # "graft" | "synthetic"
    hotspots: List[str] = field(default_factory=list)
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)
    force_verify: bool = False
    force_branch: bool = False
    force_retrieve: bool = False
    block_finalize: bool = False
    nudge: str = ""
    mean_entropy: Optional[float] = None
    n_frames: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.decision.label,
            "source": self.decision.source,
            "reason": self.decision.reason,
            "zscores": self.decision.zscores,
            "mode": self.mode,
            "hotspots": self.hotspots[:6],
            "memory_hits": len(self.memory_hits),
            "force_verify": self.force_verify,
            "force_branch": self.force_branch,
            "force_retrieve": self.force_retrieve,
            "block_finalize": self.block_finalize,
            "mean_entropy": self.mean_entropy,
            "n_frames": self.n_frames,
        }


def _synthetic_frames(
    *,
    exit_ok: bool,
    thrash: int,
    green_runs: int,
    failed_runs: int,
    stderr: str,
    contract_failed: bool,
    budget_frac: float,
) -> List[TelemetryFrame]:
    """Honest proxies for the four NFET observables when the graft is offline.

    These are NOT fake confidence — they are deterministic encodings of the
    sandbox loop's own evidence, scaled into the same ranges the policy expects.
    """
    # Entropy: high when failing / thrashing / contract miss; low when green.
    if not exit_ok:
        base_e = 3.2 + min(thrash, 3) * 0.45
    elif contract_failed:
        base_e = 2.6
    elif green_runs >= 2 and failed_runs == 0:
        base_e = 1.1
    else:
        base_e = 1.8
    # Drift: jumps on syntax/assert failures (representation "moved").
    err = (stderr or "").lower()
    if "syntaxerror" in err or "indentationerror" in err:
        drift = 0.35
    elif "assertionerror" in err or "traceback" in err:
        drift = 0.22
    elif not exit_ok:
        drift = 0.18
    elif contract_failed:
        drift = 0.14
    else:
        drift = 0.04
    # Gate: surface-heavy when the model is flailing (protocol bleed, rewrites).
    gate = 0.85 if thrash >= 2 else (0.55 if exit_ok else 0.72)
    # Regime: collapse (low entropy) when stuck in a rut; high when exploring.
    if thrash >= 2:
        regime = 0.4
    elif budget_frac > 0.7 and not exit_ok:
        regime = 0.55
    else:
        regime = 1.6 if exit_ok else 1.1

    # Emit a short sequence so rolling sustain windows have something to work on.
    frames = []
    for i in range(6):
        # Mild progression so z-scores have structure.
        frames.append(TelemetryFrame(
            logit_entropy=base_e + (0.05 if not exit_ok else -0.03) * i,
            hidden_drift=max(0.0, drift + (0.01 if not exit_ok else -0.005) * i),
            gate_mean=gate,
            regime_entropy=regime + (0.02 * (i % 3)),
            step=i + 1,
        ))
    return frames


def _graft_frames(backbone: Any, graft: Any, text: str,
                  max_tokens: int = 768) -> Tuple[List[TelemetryFrame], List[Dict[str, Any]]]:
    """Re-read text through the graft; return frames + raw traces."""
    if backbone is None or graft is None or not (text or "").strip():
        return [], []
    try:
        from local_ui.claude_reasoner import telemetry_traces_from_text
        traces = telemetry_traces_from_text(backbone, graft, text, max_tokens=max_tokens)
    except Exception:
        return [], []
    frames = [
        TelemetryFrame.from_trace(t, step=i + 1)
        for i, t in enumerate(traces)
    ]
    return frames, traces


def _hotspots_from_traces(text: str, traces: List[Dict[str, Any]],
                          max_spans: int = 5) -> List[str]:
    """Map high-entropy tokens back to short source snippets."""
    if not traces or not text:
        return []
    try:
        # Prefer the real confidence_map when available.
        # We only have traces here; approximate via char windows.
        ent = [float(t.get("graft_entropy") or t.get("logit_entropy") or 0.0)
               for t in traces]
        if len(ent) < 4:
            return []
        body = ent[2:]
        mu = sum(body) / len(body)
        var = sum((e - mu) ** 2 for e in body) / max(len(body) - 1, 1)
        sd = max(var ** 0.5, 1e-6)
        # Token-to-char is approximate without tokenizer offsets: take high-z
        # regions as proportional slices of the source.
        n = len(ent)
        hot_idx = [i for i, e in enumerate(ent) if i >= 2 and (e - mu) / sd >= 0.9]
        if not hot_idx:
            return []
        spans: List[str] = []
        # Cluster contiguous indices.
        cluster: List[int] = [hot_idx[0]]
        clusters: List[List[int]] = []
        for i in hot_idx[1:]:
            if i == cluster[-1] + 1:
                cluster.append(i)
            else:
                clusters.append(cluster)
                cluster = [i]
        clusters.append(cluster)
        for cl in clusters[:max_spans]:
            a, b = cl[0] / n, (cl[-1] + 1) / n
            start = max(0, int(a * len(text)) - 20)
            end = min(len(text), int(b * len(text)) + 20)
            frag = text[start:end].strip().replace("\n", " ")
            if len(frag) >= 12:
                spans.append(frag[:120])
        return spans
    except Exception:
        return []


def retrieve_code_memory(task: str, error: str = "", limit: int = 4) -> List[Dict[str, Any]]:
    """Pull similar past code receipts from the sealed ledger."""
    try:
        from local_ui import code_receipts as ledger
        rows = ledger.tail(80)
    except Exception:
        return []
    task_l = (task or "").lower()
    err_l = (error or "").lower()
    # Keywords from task + error type.
    keys = set(re.findall(r"[a-zA-Z_]{4,}", task_l))
    for m in re.finditer(r"(SyntaxError|AssertionError|ValueError|TypeError|"
                         r"NameError|ModuleNotFoundError|ZeroDivisionError)",
                         error or ""):
        keys.add(m.group(1).lower())
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for row in rows:
        blob = " ".join([
            str(row.get("task") or ""),
            str(row.get("summary") or ""),
            str(row.get("verdict") or ""),
            " ".join(str(x) for x in (row.get("files") or [])[:8]),
        ]).lower()
        score = sum(1 for k in keys if k in blob)
        if row.get("ok") or row.get("verdict") == "shipped":
            score += 1
        if err_l and any(tok in blob for tok in err_l.split()[:6] if len(tok) > 4):
            score += 2
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, row in scored[:limit]:
        out.append({
            "score": score,
            "task": (row.get("task") or "")[:160],
            "verdict": row.get("verdict"),
            "ok": row.get("ok"),
            "files": (row.get("files") or [])[:6],
            "summary": (row.get("summary") or "")[:160],
            "receipt_sha": row.get("receipt_sha") or row.get("ledger_sha"),
        })
    return out


class CodeNFET:
    """Stateful NFET controller for one coding run."""

    def __init__(
        self,
        backbone: Any = None,
        graft: Any = None,
        head_trained: bool = False,
        *,
        prefer_graft: bool = True,
    ):
        self.backbone = backbone
        self.graft = graft
        self.head_trained = bool(head_trained)
        self.prefer_graft = prefer_graft and backbone is not None and graft is not None
        self.policy = NFETControlPolicy(_CODE_POLICY)
        self.timeline: List[Dict[str, Any]] = []
        self._last: Optional[CodingControl] = None
        self._verify_debt = 0   # verify decisions not yet satisfied
        self._branch_debt = 0

    @property
    def available_graft(self) -> bool:
        return self.backbone is not None and self.graft is not None

    def checkpoint(
        self,
        *,
        source: str = "",
        task: str = "",
        exit_ok: bool = False,
        thrash: int = 0,
        green_runs: int = 0,
        failed_runs: int = 0,
        stderr: str = "",
        stdout: str = "",
        contract_failed: bool = False,
        budget_frac: float = 0.0,
        phase: str = "work",  # plan | work | result
    ) -> CodingControl:
        """Observe current coding state; return a control decision + actions."""
        mode = "synthetic"
        traces: List[Dict[str, Any]] = []
        frames: List[TelemetryFrame] = []
        mean_e: Optional[float] = None

        # Prefer real graft re-read of the *code* (not the error), which is
        # where LOLM's unique signal lives.
        if self.prefer_graft and (source or "").strip():
            frames, traces = _graft_frames(self.backbone, self.graft, source)
            if frames:
                mode = "graft"
                mean_e = sum(f.logit_entropy for f in frames) / len(frames)

        if not frames:
            frames = _synthetic_frames(
                exit_ok=exit_ok, thrash=thrash, green_runs=green_runs,
                failed_runs=failed_runs, stderr=stderr,
                contract_failed=contract_failed, budget_frac=budget_frac,
            )
            mode = "synthetic"
            mean_e = sum(f.logit_entropy for f in frames) / len(frames)

        self.policy.observe_all(frames)
        # Control logits from graft head when present.
        control_logits = None
        if traces:
            try:
                acc = [0.0] * 5
                n = 0
                for t in traces:
                    cl = t.get("control_logits")
                    if isinstance(cl, (list, tuple)) and len(cl) >= 5:
                        for i in range(5):
                            acc[i] += float(cl[i])
                        n += 1
                if n:
                    control_logits = [x / n for x in acc]
            except Exception:
                control_logits = None

        decision = self.policy.decide(
            control_logits=control_logits,
            head_trained=self.head_trained and control_logits is not None,
        )

        # Coding-specific guards: never finalize a red run; never continue
        # thrashing without a branch/verify.
        if phase == "result" and exit_ok and not contract_failed:
            # Promote finalize when the sandbox evidence is already green.
            if decision.control in (CONTROL_CONTINUE, CONTROL_FINALIZE):
                decision = ControlDecision(
                    control=CONTROL_FINALIZE,
                    label="finalize",
                    source=decision.source + "+sandbox",
                    reason="sandbox green + contract ok — finalize eligible",
                    zscores=decision.zscores,
                    head_probs=decision.head_probs,
                    step=decision.step,
                )
        if not exit_ok and decision.control == CONTROL_FINALIZE:
            decision = ControlDecision(
                control=CONTROL_VERIFY if thrash < 2 else CONTROL_BRANCH,
                label="verify" if thrash < 2 else "branch",
                source=decision.source + "+guard",
                reason="blocked finalize on a failing run",
                zscores=decision.zscores,
                head_probs=decision.head_probs,
                step=decision.step,
            )
        # Thrash outranks retrieve/continue/finalize: if the same error is
        # recurring, more evidence will not help — change approach.
        if thrash >= 2 and decision.control != CONTROL_BRANCH:
            decision = ControlDecision(
                control=CONTROL_BRANCH,
                label="branch",
                source=decision.source + "+thrash",
                reason="same error recurring — force branch (re-ensemble)",
                zscores=decision.zscores,
                head_probs=decision.head_probs,
                step=decision.step,
            )
        if contract_failed and decision.control in (CONTROL_CONTINUE, CONTROL_FINALIZE):
            decision = ControlDecision(
                control=CONTROL_VERIFY,
                label="verify",
                source=decision.source + "+contract",
                reason="TASK contract still failing — force verify",
                zscores=decision.zscores,
                head_probs=decision.head_probs,
                step=decision.step,
            )

        hotspots = _hotspots_from_traces(source, traces) if traces else []
        memory_hits: List[Dict[str, Any]] = []
        force_verify = decision.control == CONTROL_VERIFY
        force_branch = decision.control == CONTROL_BRANCH
        force_retrieve = decision.control == CONTROL_RETRIEVE
        block_finalize = decision.control != CONTROL_FINALIZE

        if force_retrieve or (not exit_ok and thrash >= 1):
            memory_hits = retrieve_code_memory(task, stderr)

        if force_verify:
            self._verify_debt = max(self._verify_debt, 1)
        if force_branch:
            self._branch_debt = max(self._branch_debt, 1)

        nudge = self._build_nudge(
            decision, hotspots, memory_hits, exit_ok=exit_ok,
            contract_failed=contract_failed, mode=mode, mean_e=mean_e,
        )

        ctrl = CodingControl(
            decision=decision,
            mode=mode,
            hotspots=hotspots,
            memory_hits=memory_hits,
            force_verify=force_verify or self._verify_debt > 0,
            force_branch=force_branch or self._branch_debt > 0,
            force_retrieve=force_retrieve,
            block_finalize=block_finalize and not (exit_ok and not contract_failed),
            nudge=nudge,
            mean_entropy=round(mean_e, 4) if mean_e is not None else None,
            n_frames=len(frames),
        )
        self._last = ctrl
        self.timeline.append(ctrl.to_dict())
        return ctrl

    def mark_verified(self) -> None:
        self._verify_debt = 0

    def mark_branched(self) -> None:
        self._branch_debt = 0

    def allow_finalize(self, *, exit_ok: bool, contract_ok: bool) -> bool:
        if not exit_ok or not contract_ok:
            return False
        if self._verify_debt > 0:
            return False
        if self._last is None:
            return True
        # After green evidence, finalize is allowed even if last raw decision
        # was continue — sandbox proof outranks a single quiet frame.
        return self._last.decision.control in (
            CONTROL_FINALIZE, CONTROL_CONTINUE, CONTROL_VERIFY,
        ) or (exit_ok and contract_ok)

    def receipt_blob(self) -> Dict[str, Any]:
        """Compact control timeline for the sealed code receipt."""
        labels = [t.get("label") for t in self.timeline]
        counts: Dict[str, int] = {}
        for lab in labels:
            counts[lab] = counts.get(lab, 0) + 1
        return {
            "nfet_coding": True,
            "mode": (self._last.mode if self._last else "none"),
            "graft_available": self.available_graft,
            "n_decisions": len(self.timeline),
            "counts": counts,
            "timeline": self.timeline[-24:],
            "last": self._last.to_dict() if self._last else None,
        }

    def _build_nudge(
        self,
        decision: ControlDecision,
        hotspots: List[str],
        memory_hits: List[Dict[str, Any]],
        *,
        exit_ok: bool,
        contract_failed: bool,
        mode: str,
        mean_e: Optional[float],
    ) -> str:
        lines = [
            f"\n\n── NFET CONTROL ({mode}) → {decision.label.upper()} ──",
            f"why: {decision.reason}",
        ]
        if mean_e is not None:
            lines.append(f"mean measured entropy: {mean_e:.3f}")
        if decision.zscores:
            z = decision.zscores
            lines.append(
                "z: entropy={entropy:.2f} drift={drift:.2f} "
                "gate={gate:.2f} regime={regime:.2f}".format(**{
                    k: float(z.get(k, 0.0)) for k in
                    ("entropy", "drift", "gate", "regime")
                })
            )

        if decision.control == CONTROL_RETRIEVE:
            lines.append(
                "ACTION: gather evidence before rewriting. Re-READ every file "
                "in CURRENT WORKSPACE. Use the past sealed runs below if present."
            )
            for h in memory_hits[:3]:
                lines.append(
                    f"  · past [{h.get('verdict')}] {(h.get('task') or '')[:100]}"
                    f" files={','.join(h.get('files') or [])}"
                )
            if not memory_hits:
                lines.append(
                    "  · no similar past receipts — re-read the TASK and list "
                    "every example + reject case before editing."
                )
        elif decision.control == CONTROL_VERIFY:
            lines.append(
                "ACTION: verify before trusting this draft. Run a self-check that "
                "covers EVERY example and EVERY reject case the TASK named. "
                "Do NOT say DONE. Prefer EDIT over blind rewrite."
            )
            if contract_failed:
                lines.append("  · contract probe is already red — fix those cases first.")
            if hotspots:
                lines.append("  · measured low-confidence regions in the source:")
                for s in hotspots[:4]:
                    lines.append(f"      «{s}»")
        elif decision.control == CONTROL_BRANCH:
            lines.append(
                "ACTION: branch — the current approach is in a rut. Produce a "
                "MATERIALLY DIFFERENT implementation (not a micro-edit of the "
                "broken one). A repair ensemble race may fire automatically."
            )
        elif decision.control == CONTROL_FINALIZE:
            if exit_ok and not contract_failed:
                lines.append(
                    "ACTION: finalize eligible — sandbox green and contract holds. "
                    "You may DONE after one clean RUN."
                )
            else:
                lines.append(
                    "ACTION: finalize deferred until the run is green and the "
                    "TASK contract holds."
                )
        else:
            lines.append("ACTION: continue the write→run→fix loop.")
            if hotspots and not exit_ok:
                lines.append("  · focus repairs on measured hot regions:")
                for s in hotspots[:3]:
                    lines.append(f"      «{s}»")

        lines.append("── end NFET ──\n")
        return "\n".join(lines)


def build_code_nfet(
    state_fn: Optional[Callable[[], Any]] = None,
) -> Optional[CodeNFET]:
    """Factory used by code_routes — never raises, never blocks the agent."""
    backbone = graft = None
    head_trained = False
    if state_fn is not None:
        try:
            st = state_fn()
            backbone = getattr(st, "backbone", None)
            graft = getattr(st, "graft", None)
            head_trained = bool(getattr(st, "head_trained", False))
        except Exception:
            pass
    # Always return a controller — synthetic mode works without the graft.
    return CodeNFET(backbone=backbone, graft=graft, head_trained=head_trained)
