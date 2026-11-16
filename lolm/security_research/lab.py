"""Read-only defensive event anomaly lab with reproducible comparisons.

This is a deterministic **heuristic research baseline**, not an inference path
through trained LOLM weights. Inputs are untrusted observations, never prompts.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Iterable, Sequence

EVENT_TYPES = frozenset({
    "login_failed", "login_success", "privilege_grant", "bulk_export",
    "token_used", "http_request", "ordinary_action",
})
MODES = frozenset({"rules", "shift", "hybrid"})
MAX_LINES = 200_000
MAX_LINE_BYTES = 16_384


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class Event:
    ts: int
    actor: str
    kind: str
    source: str = "synthetic"
    user_agent: str = ""
    remote: bool = False
    truth: bool = False             # evaluation label, never used in detection

    @classmethod
    def parse(cls, obj: dict[str, Any]) -> "Event":
        if not isinstance(obj, dict):
            raise ValueError("each event must be a JSON object")
        if type(obj.get("ts")) is not int or not 0 <= obj["ts"] <= 4_102_444_800:
            raise ValueError("ts must be a UTC Unix timestamp between 1970 and 2100")
        actor, kind = obj.get("actor"), obj.get("kind")
        if not isinstance(actor, str) or not 1 <= len(actor) <= 128:
            raise ValueError("actor must be 1-128 characters")
        if kind not in EVENT_TYPES:
            raise ValueError("unsupported event kind")
        for k in ("source", "user_agent"):
            if not isinstance(obj.get(k, ""), str) or len(obj.get(k, "")) > 512:
                raise ValueError(f"invalid {k}")
        for k in ("remote", "truth"):
            if type(obj.get(k, False)) is not bool:
                raise ValueError(f"{k} must be boolean")
        return cls(ts=obj["ts"], actor=actor, kind=kind,
                   source=obj.get("source", "unknown"),
                   user_agent=obj.get("user_agent", ""),
                   remote=obj.get("remote", False), truth=obj.get("truth", False))


def parse_jsonl(lines: Iterable[str]) -> list[Event]:
    out: list[Event] = []
    previous = -1
    for number, line in enumerate(lines, 1):
        if number > MAX_LINES:
            raise ValueError("event limit exceeded")
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError(f"line {number} too large")
        if not line.strip():
            continue
        try:
            event = Event.parse(json.loads(line))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid event at line {number}: {exc}") from exc
        if event.ts < previous:
            raise ValueError(f"events not chronological at line {number}")
        previous = event.ts
        out.append(event)
    return out


@dataclass
class _ActorState:
    failures: deque[int]
    last_grant: int | None = None
    shift: float = 0.0
    background: float = 0.0


def _signal(event: Event) -> float:
    # Explicitly ignore the text in user_agent/source: never interpret as instructions.
    return {"login_failed": 1.0, "privilege_grant": 2.0,
            "bulk_export": 2.0, "token_used": 0.75 if event.remote else 0.0}.get(event.kind, 0.0)


def _rules(event: Event, state: _ActorState) -> list[str]:
    cues: list[str] = []
    if event.kind == "login_failed" and len(state.failures) >= 4:
        cues.append("concentrated authentication failures")
    if event.kind == "privilege_grant" and len(state.failures) >= 2:
        cues.append("privilege change after authentication failures")
    if event.kind == "bulk_export" and state.last_grant is not None and event.ts - state.last_grant <= 900:
        cues.append("bulk export after a recent privilege change")
    # ARTEX-specific cue is evidence, never proof; can be spoofed/changed.
    if event.kind == "http_request" and event.user_agent == "artex-enrich/1.0":
        cues.append("known ARTEX enrichment client user agent (unverified)")
    return cues


def analyze(events: Sequence[Event], mode: str = "hybrid") -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError("mode must be rules, shift, or hybrid")
    state: dict[str, _ActorState] = defaultdict(lambda: _ActorState(deque()))
    findings: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    prev_hash = "0" * 64
    for idx, event in enumerate(events):
        st = state[event.actor]
        while st.failures and event.ts - st.failures[0] > 300:
            st.failures.popleft()
        if event.kind == "login_failed":
            st.failures.append(event.ts)
        reasons = _rules(event, st)
        if event.kind == "privilege_grant":
            st.last_grant = event.ts
        value = _signal(event)
        # Nonnegative one-sided CUSUM analogue; no privileged model outputs involved.
        st.shift = max(0.0, min(100.0, 0.87 * st.shift + value - st.background - 0.32))
        st.background = 0.98 * st.background + 0.02 * value
        shifted = st.shift >= 3.0 and value > 0
        detected = bool(reasons) if mode == "rules" else shifted if mode == "shift" else bool(reasons) or shifted
        selected = (reasons if mode != "shift" else []) + (["positive security-signal regime shift"] if shifted and mode != "rules" else [])
        record = {"index": idx, "ts": event.ts, "actor": event.actor, "detected": detected,
                  "reasons": selected if detected else [], "shift_score": round(st.shift, 4)}
        # Hash-only event reference prevents receipts from replicating sensitive raw log text.
        event_hash = hashlib.sha256(canonical(asdict(event))).hexdigest()
        receipt_payload = {"previous_hash": prev_hash, "event_hash": event_hash,
                           "mode": mode, "decision": record}
        prev_hash = hashlib.sha256(canonical(receipt_payload)).hexdigest()
        receipts.append({**receipt_payload, "hash": prev_hash})
        if detected:
            findings.append(record)
    return {"schema": "lolm-security-lab/v1", "implementation": "heuristic-only",
            "lolm_checkpoint_attached": False, "mode": mode, "count": len(events),
            "findings": findings, "receipts": receipts, "head": prev_hash}


def verify_receipts(receipts: Sequence[dict[str, Any]], expected_head: str | None = None) -> bool:
    previous = "0" * 64
    for receipt in receipts:
        if receipt.get("previous_hash") != previous:
            return False
        payload = {key: receipt.get(key) for key in ("previous_hash", "event_hash", "mode", "decision")}
        if any(not isinstance(payload[k], (dict if k == "decision" else str)) for k in payload):
            return False
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        if digest != receipt.get("hash"):
            return False
        previous = digest
    return expected_head is None or previous == expected_head


def synthetic_scenarios(seed: int = 37) -> list[Event]:
    """Deterministic, fictional records. Scenarios are not replayed real attacks."""
    import random
    rng = random.Random(seed)
    out: list[Event] = []
    t0 = 1_800_000_000
    for i in range(80):
        out.append(Event(t0 + i * 30, f"employee-{i % 9}",
                         rng.choice(["ordinary_action", "login_success", "http_request"])))
    t = t0 + 80 * 30
    # High-volume failed auths, a privileged change, then a suspicious export.
    for j in range(10):
        out.append(Event(t + j * 13, "synthetic-compromised-account", "login_failed", truth=True))
    out.append(Event(t + 135, "synthetic-compromised-account", "privilege_grant", truth=True))
    out.append(Event(t + 150, "synthetic-compromised-account", "bulk_export", truth=True))
    # Separate short burst and a spoofable ARTEX user-agent cue.
    for j in range(4):
        out.append(Event(t + 190 + j * 14, "synthetic-remote-token", "token_used", remote=True, truth=True))
    out.append(Event(t + 260, "web-observation", "http_request", user_agent="artex-enrich/1.0", truth=True))
    for i in range(60):
        out.append(Event(t + 300 + i * 30, f"employee-{i % 9}",
                         rng.choice(["ordinary_action", "login_success", "http_request"])))
    return out


def _metrics(events: Sequence[Event], result: dict[str, Any]) -> dict[str, float | int | None]:
    detected_indices = {r["index"] for r in result["findings"]}
    tp = sum(e.truth and i in detected_indices for i, e in enumerate(events))
    fp = sum(not e.truth and i in detected_indices for i, e in enumerate(events))
    fn = sum(e.truth and i not in detected_indices for i, e in enumerate(events))
    tn = sum(not e.truth and i not in detected_indices for i, e in enumerate(events))
    prec = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 4), "recall": round(recall, 4),
            "f1": round(2 * prec * recall / (prec + recall), 4) if prec + recall else 0.0,
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0}


def benchmark(seeds: Sequence[int] = (17, 37, 53, 101)) -> dict[str, Any]:
    """Matched comparison over identical held-out synthetic event streams."""
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        events = synthetic_scenarios(seed)
        for mode in ("rules", "shift", "hybrid"):
            result = analyze(events, mode)
            assert verify_receipts(result["receipts"], result["head"])
            rows.append({"seed": seed, "mode": mode, **_metrics(events, result)})
    summary = {}
    for mode in MODES:
        sub = [r for r in rows if r["mode"] == mode]
        summary[mode] = {k: round(sum(float(r[k]) for r in sub) / len(sub), 4)
                         for k in ("precision", "recall", "f1", "false_positive_rate")}
    return {"suite": "synthetic-v1", "data_origin": "fictional", "neural_model": False,
            "seeds": list(seeds), "results": summary, "runs": rows}
