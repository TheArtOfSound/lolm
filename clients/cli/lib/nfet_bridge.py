#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persistent JSONL bridge from the npm CLI to the real LOLM-NFET monitor.

This process loads the local backbone and trained graft once, then replays each
external provider answer through the same entropy/drift/gate/regime formulas and
NFETControlPolicy used by the Python agent. It never invents telemetry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path


def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


def aggregate_logits(traces, tail=32):
    from lolm.nfet_policy import softmax
    rows = [row.get("control_logits") for row in traces]
    rows = [row for row in rows if isinstance(row, list) and len(row) == 5]
    if not rows:
        return None
    probs = [softmax([float(v) for v in row]) for row in rows[-max(1, tail):]]
    means = [sum(row[i] for row in probs) / len(probs) for i in range(5)]
    return [math.log(max(value, 1e-12)) for value in means]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--profile", default="qwen3_4b_lab")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--checkpoint", default="runs/nfet_controller/live_qwen4b.pt")
    parser.add_argument("--backend", default="gru_debug")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    sys.path.insert(0, str(root))
    from local_ui import server as workspace
    from local_ui.claude_reasoner import telemetry_traces_from_text
    from lolm.nfet_policy import (
        CONTROL_CONTINUE,
        CONTROL_FINALIZE,
        ControlDecision,
        NFETControlPolicy,
        TelemetryFrame,
    )

    checkpoint = Path(args.checkpoint).expanduser()
    if not checkpoint.is_absolute():
        checkpoint = root / checkpoint
    result = workspace.load_model(workspace.LoadRequest(
        profile=args.profile,
        device=args.device,
        graft_checkpoint=str(checkpoint),
        latent_backend=args.backend,
    ))
    if not result.get("loaded"):
        raise RuntimeError(result.get("warning") or "NFET model failed to load")

    policy = NFETControlPolicy()
    last_text_sha = ""
    last_traces = None
    emit({
        "event": "ready",
        "profile": workspace.STATE.profile,
        "device": str(workspace.STATE.device),
        "backend": workspace.STATE.latent_backend,
        "head_trained": workspace.STATE.head_trained,
        "checkpoint": str(checkpoint),
    })

    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            if request.get("op") == "close":
                emit({"event": "closed"})
                return
            if request.get("op") == "status":
                emit({
                    "event": "status",
                    "loaded": True,
                    "profile": workspace.STATE.profile,
                    "device": str(workspace.STATE.device),
                    "backend": workspace.STATE.latent_backend,
                    "head_trained": workspace.STATE.head_trained,
                })
                continue
            text = str(request.get("text") or "").strip()
            checkpoint_kind = str(request.get("checkpoint") or "work").lower()
            verified = bool(request.get("verified"))
            if not text:
                raise ValueError("text must not be empty")
            if checkpoint_kind not in {"plan", "work", "result"}:
                raise ValueError("checkpoint must be plan, work, or result")
            if request.get("reset"):
                policy = NFETControlPolicy()
                last_text_sha = ""
                last_traces = None

            text_sha = hashlib.sha256(text.encode()).hexdigest()
            reuse = bool(request.get("reuse")) and text_sha == last_text_sha and last_traces
            if reuse:
                traces = last_traces
            else:
                traces = telemetry_traces_from_text(
                    workspace.STATE.backbone,
                    workspace.STATE.graft,
                    text,
                    max_tokens=max(32, min(int(request.get("max_tokens") or 1024), 4096)),
                )
            frames = [TelemetryFrame.from_trace(row, step=i + 1) for i, row in enumerate(traces)]
            if not frames:
                raise RuntimeError("LOLM produced no telemetry frames")
            if not reuse:
                policy.observe_all(frames)
                last_text_sha = text_sha
                last_traces = traces
            decision = policy.decide(
                control_logits=aggregate_logits(traces),
                head_trained=workspace.STATE.head_trained,
            )

            # Keep the same safety/completion gates as the MCP monitor. A pointwise
            # head may not force disruptive action without rolling telemetry support.
            z = decision.zscores
            cfg = policy.cfg
            unsupported = ""
            if decision.source == "head":
                if decision.label == "retrieve" and z.get("entropy", 0) < cfg.entropy_spike_z:
                    unsupported = "retrieve lacked sustained entropy"
                elif decision.label == "verify" and (
                    z.get("drift", 0) < cfg.drift_spike_z
                    or z.get("entropy", 0) < cfg.verify_entropy_z
                ):
                    unsupported = "verify lacked drift and uncertainty"
                elif decision.label == "branch" and (
                    z.get("regime", 0) > cfg.regime_stall_z
                    or z.get("entropy", 0) < cfg.branch_entropy_z
                ):
                    unsupported = "branch lacked a supported regime stall"
            if unsupported:
                decision = ControlDecision(
                    CONTROL_CONTINUE, "continue", "telemetry_guard",
                    f"{unsupported}; continued instead", z,
                    head_probs=decision.head_probs, step=decision.step,
                )
            if decision.control == CONTROL_FINALIZE and not (checkpoint_kind == "result" and verified):
                decision = ControlDecision(
                    CONTROL_CONTINUE, "continue", "completion_guard",
                    "finalize requires a verified result", z,
                    head_probs=decision.head_probs, step=decision.step,
                )
            elif checkpoint_kind == "result" and verified and decision.control == CONTROL_CONTINUE:
                decision = ControlDecision(
                    CONTROL_FINALIZE, "finalize", "verified_result",
                    "normal checks passed and telemetry raised no supported intervention", z,
                    head_probs=decision.head_probs, step=decision.step,
                )

            def mean(key):
                values = [float(row[key]) for row in traces if row.get(key) is not None]
                return round(sum(values) / len(values), 6) if values else 0.0

            emit({
                "event": "decision",
                "id": f"nfet-{time.time_ns()}",
                "text_sha256": text_sha,
                "telemetry_reused": bool(reuse),
                "observed_tokens": len(frames),
                "frames_seen": policy.frames_seen,
                "head_trained": workspace.STATE.head_trained,
                "checkpoint": checkpoint_kind,
                "verified": verified,
                "decision": decision.to_dict(),
                "telemetry": {
                    "avg_entropy": mean("graft_entropy"),
                    "avg_hidden_drift": mean("hidden_drift"),
                    "avg_gate": mean("gate_mean"),
                    "avg_regime_entropy": mean("regime_entropy"),
                },
            })
        except Exception as exc:
            emit({"event": "error", "error": str(exc)[:800]})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit({"event": "fatal", "error": str(exc)[:1000]})
        raise
