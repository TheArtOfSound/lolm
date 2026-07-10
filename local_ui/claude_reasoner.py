"""Frontier reasoner backend: Claude generates, LOLM-NFET watches.

This module gives the workspace a second brain without changing any consumer:
it implements the exact generation-loop event protocol (`start`/`token`/`done`
events with NFET traces) that the chat server, orchestrator, and NFET agent
already speak. Claude (via the official Anthropic SDK) produces the text; the
local frozen backbone + graft then re-read that text to produce per-token NFET
telemetry — entropy, drift, gate, regime, control logits. The local latent
machinery becomes the monitor and controller; the frontier model is the voice.

Requires `pip install anthropic` and an `ANTHROPIC_API_KEY` (or `ant auth
login` profile). Without a local model loaded, generation still works but
telemetry is empty, so NFET control degrades to budget-driven continue.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"


def _split_messages(messages: List[Any]) -> Tuple[str, List[Dict[str, str]]]:
    """Map workspace chat messages onto the Claude API shape."""
    system_parts: List[str] = []
    turns: List[Dict[str, str]] = []
    for msg in messages:
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else "user")
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
        content = (content or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            turns.append({"role": role, "content": content})
        else:
            turns.append({"role": "user", "content": content})
    if not turns:
        turns = [{"role": "user", "content": "(empty)"}]
    if turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": "(context above)"})
    return "\n\n".join(system_parts), turns


def telemetry_traces_from_text(backbone: Any, graft: Any, text: str,
                               max_tokens: int = 1024) -> List[Dict[str, Any]]:
    """Re-read arbitrary text through the local backbone+graft for telemetry.

    Returns one generation-loop-shaped token trace per backbone token, with
    real per-position entropy, lag-1 hidden drift, gate mean, regime entropy,
    and control logits. This is how the local latent controller observes a
    frontier model's output.
    """
    import torch
    import torch.nn.functional as F

    if backbone is None or graft is None or not text.strip():
        return []
    param = next(graft.parameters())
    batch = backbone.tokenizer(text, return_tensors="pt", truncation=True,
                               max_length=max_tokens)
    input_ids = batch["input_ids"].to(param.device)
    with torch.no_grad():
        base = backbone(input_ids=input_ids)
        hidden = base.hidden_states.to(device=param.device, dtype=param.dtype)
        logits = base.logits.to(device=param.device, dtype=param.dtype)
        out = graft(hidden, base_logits=logits)
        corrected = out.corrected_hidden[0].float()                      # (T, d)
        log_probs = F.log_softmax(base.logits[0].float(), dim=-1)
        entropy = -(log_probs.exp() * log_probs).sum(dim=-1)            # (T,)
        gate = out.gate[0].float().mean(dim=-1)                          # (T,)
        probs = out.regime_probs[0].float().clamp_min(1e-8)
        regime = -(probs * probs.log()).sum(dim=-1)                      # (T,)
        drift = torch.zeros_like(entropy)
        drift[1:] = (corrected[1:] - corrected[:-1]).pow(2).mean(dim=-1)
        # Per-position control logits through the head's exact feature layout.
        features = torch.cat([
            corrected,
            entropy[:, None], drift[:, None], gate[:, None], regime[:, None],
        ], dim=-1).to(dtype=param.dtype)
        control_logits = graft.nfet.head(features).float()               # (T, 5)

    ids = input_ids[0].tolist()
    traces: List[Dict[str, Any]] = []
    for t, token_id in enumerate(ids):
        traces.append({
            "step": t + 1,
            "used_graft": True,
            "monitor": "lolm_nfet_replay",
            "token_id": token_id,
            "graft_entropy": round(float(entropy[t]), 4),
            "hidden_drift": round(float(drift[t]), 6),
            "gate_mean": round(float(gate[t]), 4),
            "regime_entropy": round(float(regime[t]), 4),
            "control_logits": [round(float(x), 4) for x in control_logits[t].tolist()],
        })
    return traces


class ClaudeReasonerLoop:
    """Generation loop backed by Claude, telemetered by the local graft.

    Drop-in replacement for the local `generation_loop`: same request object
    in, same event protocol out. `state_fn` returns the live runtime state
    (anything with `.backbone` and `.graft`) so telemetry always uses the
    currently loaded local model.
    """

    def __init__(self, state_fn: Callable[[], Any],
                 model: str = DEFAULT_CLAUDE_MODEL,
                 client: Optional[Any] = None,
                 adaptive_thinking: bool = False):
        self.state_fn = state_fn
        self.model = model
        self._client = client
        self._client_injected = client is not None   # tests inject a fake — never rebuild it
        self._client_key: Optional[str] = None
        self.adaptive_thinking = adaptive_thinking

    def _get_client(self) -> Any:
        # HOT-APPLY: rebuild the SDK client when ANTHROPIC_API_KEY changes (a key
        # saved/rotated in the Keys panel works on the next request, no restart).
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if self._client is None or (not self._client_injected and key != self._client_key):
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError(
                    "The Claude reasoner needs the anthropic SDK: pip install anthropic"
                ) from exc
            self._client = anthropic.Anthropic()
            self._client_key = key
        return self._client

    def stream_text(self, req: Any) -> Iterator[str]:
        """Stream Claude's answer as plain-text deltas — same contract as the
        worker/direct stream paths, so the visual builder can stream from the
        user's paid Claude key. Raises on failure so the caller falls to the
        next tier."""
        client = self._get_client()
        system, turns = _split_messages(req.messages)
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max(int(getattr(req, "max_new_tokens", 640)) * 4, 256),
            "messages": turns,
        }
        if system:
            kwargs["system"] = system
        with client.messages.stream(**kwargs) as stream:
            for piece in stream.text_stream:
                if piece:
                    yield piece

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        started = time.perf_counter()
        try:
            client = self._get_client()
            system, turns = _split_messages(req.messages)
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": max(int(req.max_new_tokens) * 4, 256),
                "messages": turns,
            }
            if system:
                kwargs["system"] = system
            if self.adaptive_thinking:
                kwargs["thinking"] = {"type": "adaptive"}
            # No sampling params: temperature/top_p/top_k are removed on
            # Opus 4.7+ and return 400 if sent.
            response = client.messages.create(**kwargs)
            text = "".join(
                block.text for block in response.content
                if getattr(block, "type", None) == "text"
            ).strip()
        except Exception as exc:
            yield {"event": "error", "data": {"error": f"claude reasoner failed: {exc}"[:500]}}
            return

        state = self.state_fn()
        backbone = getattr(state, "backbone", None)
        graft = getattr(state, "graft", None)
        try:
            traces = telemetry_traces_from_text(backbone, graft, text)
        except Exception:
            traces = []

        yield {"event": "start", "data": {
            "profile": f"claude:{self.model}",
            "use_graft": bool(traces),
            "latent_backend": "monitor" if traces else None,
            "reasoner": "claude",
        }}

        gate_means: List[float] = []
        regimes: List[float] = []
        controls: List[int] = []
        if traces:
            tokenizer = backbone.tokenizer
            for trace in traces:
                piece = tokenizer.decode([trace["token_id"]])
                gate_means.append(trace["gate_mean"])
                regimes.append(trace["regime_entropy"])
                logits = trace.get("control_logits") or []
                if logits:
                    controls.append(max(range(len(logits)), key=logits.__getitem__))
                yield {"event": "token", "data": {"token": piece, "token_id": trace["token_id"], "trace": trace}}
        else:
            for piece in text.split(" "):
                yield {"event": "token", "data": {"token": piece + " ", "trace": {"used_graft": False}}}

        elapsed = max(time.perf_counter() - started, 1e-9)
        n_tokens = len(traces) or len(text.split(" "))
        usage = getattr(response, "usage", None)
        avg_gate = sum(gate_means) / len(gate_means) if gate_means else None
        avg_regime = sum(regimes) / len(regimes) if regimes else None
        yield {"event": "done", "data": {
            "id": f"claude-{int(time.time() * 1000)}",
            "response": text,
            "tokens": n_tokens,
            "profile": f"claude:{self.model}",
            "reasoner": "claude",
            "use_graft": bool(traces),
            "seconds": elapsed,
            "claude_usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            } if usage is not None else None,
            "summary": {
                "avg_gate": avg_gate,
                "avg_surface_share": avg_gate,
                "avg_latent_share": 1.0 - avg_gate if avg_gate is not None else None,
                "avg_regime_entropy": avg_regime,
                "last_control": controls[-1] if controls else None,
            },
        }}
