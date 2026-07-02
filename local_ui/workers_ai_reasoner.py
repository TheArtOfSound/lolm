"""Frontier reasoner backed by Cloudflare Workers AI (Llama 70B).

Same idea as the Claude bridge: a strong model writes the text, the local
LOLM graft re-reads it for per-token NFET telemetry (entropy, drift, gate,
regime, control logits). The difference is the text source — here it is
``@cf/meta/llama-3.3-70b-instruct-fp8-fast`` served through the project's own
Cloudflare Worker, so the only credential the origin box holds is a shared
secret that authorizes calling that one endpoint (not the whole CF account).

Emits the exact generation-loop event protocol the NFET agent consumes, so it
is a drop-in for the local 0.6B ``generation_loop``: same request in, same
``start``/``token``/``done`` events out. Telemetry needs a local model loaded
(the 0.6B backbone + graft act as the monitor); without one, control degrades
to budget-driven continue.

Env:
    WORKERS_AI_URL     full URL of the worker /ai/generate endpoint
    WORKERS_AI_SECRET  the shared bearer secret (matches the worker's AI_SECRET)
    WORKERS_AI_MODEL   override the model id (default Llama 3.3 70B fp8 fast)
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional

from local_ui.claude_reasoner import _split_messages, telemetry_traces_from_text

DEFAULT_WORKERS_AI_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def _messages_for_workers_ai(req: Any) -> List[Dict[str, str]]:
    """Workers AI takes a flat chat array with a leading system turn."""
    system, turns = _split_messages(req.messages)
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(turns)
    return msgs


class WorkersAIReasonerLoop:
    """Generation loop backed by Cloudflare Workers AI, telemetered locally."""

    def __init__(self, state_fn: Callable[[], Any],
                 url: Optional[str] = None,
                 secret: Optional[str] = None,
                 model: Optional[str] = None,
                 timeout: float = 30.0):
        self.state_fn = state_fn
        self.url = url or os.environ.get("WORKERS_AI_URL", "")
        self.secret = secret or os.environ.get("WORKERS_AI_SECRET", "")
        self.model = model or os.environ.get("WORKERS_AI_MODEL", DEFAULT_WORKERS_AI_MODEL)
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.url and self.secret)

    def _generate(self, req: Any) -> Dict[str, Any]:
        # Cap the request. The old `max_new_tokens*3` ballooned a 3600-token visual
        # build into a 10,800-token ask that NO provider finishes inside the 30s
        # window — so every big build timed out and fell back to the tiny local
        # model (a multi-minute CPU crawl). 4096 is plenty for any game/app's HTML
        # and completes on a fast cascade provider (Groq/Cerebras) in ~15-25s.
        want = int(getattr(req, "max_new_tokens", 128))
        n_tokens = min(max(want * 3, 96), 4096)
        payload = {
            "messages": _messages_for_workers_ai(req),
            "max_tokens": n_tokens,
            "model": self.model,
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.secret}",
                     # Cloudflare's edge 403s the default Python-urllib UA.
                     "User-Agent": "lolm-nfet-origin/1.0"})
        # Scale the wait with the generation size: a 4096-token game legitimately
        # needs longer than a one-line planner turn. Bounded so a hung call can't
        # wait forever, but generous enough that a real big build isn't killed.
        eff_timeout = min(self.timeout + n_tokens / 40.0, 150.0)
        with urllib.request.urlopen(request, timeout=eff_timeout) as resp:
            return json.loads(resp.read())

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        started = time.perf_counter()
        if not self.available():
            yield {"event": "error", "data": {"error": "workers_ai reasoner not configured (URL/secret)"}}
            return
        try:
            result = self._generate(req)
            text = (result.get("text") or "").strip()
            if not text:
                raise RuntimeError(result.get("error") or "empty response")
        except Exception as exc:
            yield {"event": "error", "data": {"error": f"workers_ai reasoner failed: {exc}"[:400]}}
            return

        # The worker cascades across independent 70B providers; surface which
        # one actually answered (groq / cerebras / workers-ai / ...) honestly.
        provider = result.get("provider") or "workers-ai"
        model_label = f"{provider}:{(result.get('model') or self.model).split('/')[-1]}"

        state = self.state_fn()
        backbone = getattr(state, "backbone", None)
        graft = getattr(state, "graft", None)
        # The final answer needs no control telemetry (no decision follows it),
        # so the agent passes telemeter=False there — skipping the local 0.6B
        # re-read over the longest text, which is the main per-run latency cost.
        if getattr(req, "telemeter", True):
            try:
                traces = telemetry_traces_from_text(backbone, graft, text)
            except Exception:
                traces = []
        else:
            traces = []

        yield {"event": "start", "data": {
            "profile": model_label,
            "use_graft": bool(traces),
            "latent_backend": "monitor" if traces else None,
            "reasoner": "workers_ai",
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
        avg_gate = sum(gate_means) / len(gate_means) if gate_means else None
        avg_regime = sum(regimes) / len(regimes) if regimes else None
        yield {"event": "done", "data": {
            "id": f"wai-{int(time.time() * 1000)}",
            "response": text,
            "tokens": n_tokens,
            "profile": model_label,
            "reasoner": "workers_ai",
            "use_graft": bool(traces),
            "seconds": elapsed,
            "tok_per_sec": n_tokens / elapsed,
            "edge_ms": result.get("ms"),
            "summary": {
                "avg_gate": avg_gate,
                "avg_surface_share": avg_gate,
                "avg_latent_share": 1.0 - avg_gate if avg_gate is not None else None,
                "avg_regime_entropy": avg_regime,
                "last_control": controls[-1] if controls else None,
            },
        }}
