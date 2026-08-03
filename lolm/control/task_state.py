# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Persistent, fail-closed task state for LOLM coding runs.

The state is deliberately small and deterministic. It does not claim model-level
understanding; it records the objective, minimum completion criteria, observations,
failures, and the next control action so a resumed run does not lose its referent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "lolm.task_state.v1"


@dataclass
class Criterion:
    id: str
    text: str
    met: bool = False
    evidence: str = ""


@dataclass
class PlanStep:
    id: str
    text: str
    status: str = "open"


@dataclass
class Failure:
    step: int
    action: str
    observation: str
    ts: int


@dataclass
class TaskState:
    schema: str
    task_id: str
    objective: str
    session: str = ""
    conversation_id: str = ""
    owner_hash: str = ""
    created_ts: int = 0
    updated_ts: int = 0
    step: int = 0
    context_resets: int = 0
    interruptions: int = 0
    C: List[Criterion] = field(default_factory=list)
    P: List[PlanStep] = field(default_factory=list)
    F: List[Failure] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    last_action: str = "continue"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskState":
        row = dict(data or {})
        row["C"] = [c if isinstance(c, Criterion) else Criterion(**c) for c in row.get("C", [])]
        row["P"] = [p if isinstance(p, PlanStep) else PlanStep(**p) for p in row.get("P", [])]
        row["F"] = [f if isinstance(f, Failure) else Failure(**f) for f in row.get("F", [])]
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in row.items() if k in allowed})

    def prompt_block(self, max_chars: int = 2200) -> str:
        open_c = [c.text for c in self.C if not c.met]
        done_c = [c.text for c in self.C if c.met]
        plan = [f"{p.status}: {p.text}" for p in self.P]
        block = [
            "TASK STATE z_t (persistent; do not change the user's objective):",
            f"objective: {self.objective}",
            f"step: {self.step}",
            "open criteria: " + ("; ".join(open_c) if open_c else "none"),
            "met criteria: " + ("; ".join(done_c) if done_c else "none"),
            "plan: " + ("; ".join(plan) if plan else "inspect, act, verify, finish"),
            f"policy: {self.last_action}",
        ]
        return "\n".join(block)[:max_chars]


def _state_root() -> Path:
    configured = os.environ.get("LOLM_TASK_STATE_DIR", "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".lolm" / "task_state"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _opaque(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:20]


def _task_id(task: str, session: str, conversation_id: str, owner: str) -> str:
    identity = "\0".join([owner or "anonymous", conversation_id or session or "session", task.strip()])
    return "task_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _path(task_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", task_id)
    if not safe or safe.startswith(".") or ".." in safe:
        raise ValueError("invalid task id")
    return _state_root() / f"{safe}.json"


def _artifact_extensions(task: str) -> Optional[set[str]]:
    """Return extensions that satisfy the task's explicitly requested medium.

    ``None`` means the task is a normal repository/code task where any intentional
    file change may satisfy the artifact criterion. An explicit medium requires a
    matching deliverable, so ``main.py`` cannot satisfy a PDF or document request.
    """
    text = str(task or "").lower()
    if re.search(r"\bpdf\b", text):
        return {".pdf"}
    if re.search(r"\b(docx|word document)\b", text):
        return {".docx"}
    if re.search(r"\b(spreadsheet|xlsx|excel)\b", text):
        return {".xlsx", ".csv"}
    if re.search(r"\b(slides?|powerpoint|pptx|presentation)\b", text):
        return {".pptx"}
    if re.search(r"\b(html|webpage|web page|website)\b", text):
        return {".html", ".htm"}
    if re.search(r"\b(image|png|jpe?g|svg)\b", text):
        return {".png", ".jpg", ".jpeg", ".svg"}
    if re.search(r"\b(document|report|letter|resume|invoice)\b", text):
        return {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md"}
    return None


def _matching_artifacts(task: str, files: List[str]) -> List[str]:
    expected = _artifact_extensions(task)
    normalized = [str(path).replace("\\", "/") for path in files]
    if expected is None:
        return normalized
    return [path for path in normalized if Path(path).suffix.lower() in expected]


def observe_workspace_artifacts(state: TaskState, files: List[str]) -> List[str]:
    """Bind real workspace paths to the artifact criterion without advancing a step.

    This hook exists for files created by an executed program rather than through a
    model FILE/EDIT action. The caller must supply paths discovered from the sandbox
    filesystem. Stdout claims are deliberately insufficient. Criteria are monotonic:
    once a matching artifact has been observed, a later partial file list cannot unset
    it.
    """
    matching = _matching_artifacts(state.objective, [str(path) for path in files])
    if not matching:
        return []
    criterion = next((row for row in state.C if row.id == "artifact"), None)
    changed = bool(criterion is not None and not criterion.met)
    if criterion is not None:
        criterion.met = True
        criterion.evidence = ", ".join(matching[-8:])[:400]
    for step in state.P:
        if step.id in ("inspect", "act"):
            step.status = "done"
    state.updated_ts = int(time.time())
    state.observations.append({
        "step": state.step,
        "action": "workspace_artifact_observed",
        "observation": "matching artifact discovered from sandbox filesystem",
        "exit_ok": False,
        "produced_output": False,
        "files": [str(path) for path in files][-12:],
        "matching_artifacts": matching[-12:],
        "criterion_changed": changed,
        "ts": int(time.time()),
    })
    state.observations = state.observations[-100:]
    state.last_action = policy_action(state)["action"]
    return matching


def _criteria(task: str) -> List[Criterion]:
    text = (task or "").lower()
    expected = _artifact_extensions(task)
    artifact_text = "requested deliverable or repository change exists"
    if expected:
        artifact_text = "requested artifact type exists: " + ", ".join(sorted(expected))
    rows = [
        Criterion("artifact", artifact_text),
        Criterion("execution", "an objective verification command completed successfully"),
    ]
    if any(x in text for x in ("print", "output", "show", "generate", "create", "build", "pdf", "document")):
        rows.append(Criterion("evidence", "observable output or artifact evidence was produced"))
    return rows


def _plan(task: str) -> List[PlanStep]:
    return [
        PlanStep("inspect", "inspect the task and relevant workspace"),
        PlanStep("act", "make the smallest task-aligned change"),
        PlanStep("verify", "run an objective verifier against the result"),
        PlanStep("finish", "finish only when every criterion has evidence"),
    ]


def load_or_init(
    task: str,
    *,
    session: str = "",
    conversation_id: str = "",
    owner: str = "",
    resume: bool = True,
    context_reset: bool = False,
) -> TaskState:
    now = int(time.time())
    tid = _task_id(task, session, conversation_id, owner)
    path = _path(tid)
    if resume and path.exists():
        try:
            state = TaskState.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if context_reset:
                state.context_resets += 1
            state.updated_ts = now
            return state
        except Exception:
            # Preserve the corrupt file for forensics and open a clean state.
            try:
                path.replace(path.with_suffix(f".corrupt-{now}.json"))
            except Exception:
                pass
    return TaskState(
        schema=SCHEMA,
        task_id=tid,
        objective=(task or "").strip()[:1000],
        session=(session or "")[:160],
        conversation_id=(conversation_id or "")[:160],
        owner_hash=_opaque(owner) if owner else "",
        created_ts=now,
        updated_ts=now,
        context_resets=1 if context_reset else 0,
        C=_criteria(task),
        P=_plan(task),
    )


def save_task_state(state: TaskState) -> None:
    state.updated_ts = int(time.time())
    path = _path(state.task_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def update_task_state(
    state: TaskState,
    *,
    observation: str,
    action: str,
    result: Optional[Dict[str, Any]] = None,
) -> TaskState:
    result = dict(result or {})
    state.step += 1
    state.updated_ts = int(time.time())
    files = [str(p) for p in result.get("files") or []]
    matching = observe_workspace_artifacts(state, files)
    exit_ok = result.get("exit_ok") is True
    produced = result.get("produced_output") is True
    if exit_ok:
        c = next((x for x in state.C if x.id == "execution"), None)
        if c:
            c.met = True
            c.evidence = "green verification/run"
        for p in state.P:
            if p.id == "verify":
                p.status = "done"
    if produced:
        c = next((x for x in state.C if x.id == "evidence"), None)
        if c:
            c.met = True
            c.evidence = (observation or "observable output")[:300]
    if not exit_ok or action in ("run_fail", "error", "rejected"):
        state.F.append(Failure(
            step=state.step,
            action=action,
            observation=(observation or "failure")[-400:],
            ts=int(time.time()),
        ))
        state.F = state.F[-50:]
    state.observations.append({
        "step": state.step,
        "action": action,
        "observation": (observation or "")[-400:],
        "exit_ok": exit_ok,
        "produced_output": produced,
        "files": files[-12:],
        "matching_artifacts": matching[-12:],
        "ts": int(time.time()),
    })
    state.observations = state.observations[-100:]
    state.last_action = policy_action(state)["action"]
    if allow_finalize_from_state(state):
        for p in state.P:
            if p.id == "finish":
                p.status = "ready"
    return state


def allow_finalize_from_state(state: TaskState) -> bool:
    return bool(state.C) and all(c.met for c in state.C)


def policy_action(state: TaskState) -> Dict[str, Any]:
    open_c = [c for c in state.C if not c.met]
    recent_failures = state.F[-3:]
    repeated = len(recent_failures) >= 2 and len({f.observation for f in recent_failures}) <= 1
    if allow_finalize_from_state(state):
        return {
            "action": "finalize",
            "reason": "all persistent completion criteria have evidence",
            "block_finalize": False,
            "force_verify": False,
            "force_branch": False,
        }
    if repeated:
        return {
            "action": "branch",
            "reason": "repeated failure evidence requires a different causal strategy",
            "block_finalize": True,
            "force_verify": False,
            "force_branch": True,
        }
    missing_ids = {c.id for c in open_c}
    if "execution" in missing_ids and "artifact" not in missing_ids:
        return {
            "action": "verify",
            "reason": "a deliverable exists but objective verification is still missing",
            "block_finalize": True,
            "force_verify": True,
            "force_branch": False,
        }
    if "artifact" in missing_ids:
        return {
            "action": "continue",
            "reason": "the requested artifact type has not been produced yet",
            "block_finalize": True,
            "force_verify": False,
            "force_branch": False,
        }
    return {
        "action": "continue",
        "reason": "advance the remaining completion criteria",
        "block_finalize": True,
        "force_verify": False,
        "force_branch": False,
    }


def receipt_blob(state: TaskState) -> Dict[str, Any]:
    policy = policy_action(state)
    return {
        "schema": state.schema,
        "task_id": state.task_id,
        "objective": state.objective[:400],
        "conversation_id": state.conversation_id,
        "step": state.step,
        "context_resets": state.context_resets,
        "interruptions": state.interruptions,
        "criteria": [asdict(c) for c in state.C],
        "plan": [asdict(p) for p in state.P],
        "failure_count": len(state.F),
        "policy": policy,
        "finalize_allowed": allow_finalize_from_state(state),
        "updated_ts": state.updated_ts,
    }
