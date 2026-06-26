"""Local sovereign brain — generation from a model running on YOUR machine.

The whole point of LOLM is that nothing about it has to leave your computer. The
NFET control, memory, operator, sandbox and receipts are already on-device; the one
remaining tether is the *generator*. This module cuts it: it speaks to a local
inference server (Ollama, llama.cpp's server, LM Studio, vLLM, an MLX OpenAI shim —
anything that exposes Ollama's /api/chat or an OpenAI /v1/chat/completions) and emits
the EXACT same start/token/done protocol as the Cloudflare brain, so it is a drop-in.
The local graft still re-reads the text for per-token telemetry, identical to the
cloud path.

Run a capable open model locally (e.g. `ollama run llama3.3:70b` or `qwen2.5:72b`)
and LOLM runs with zero external calls. Set LOLM_SOVEREIGN=1 and the cloud brain is
refused entirely — the dream state: it is your own thing, on your own machine.

Env:
    LOLM_LOCAL_URL     base URL of the local server (default http://127.0.0.1:11434)
    LOLM_LOCAL_MODEL   model name to ask for (e.g. "llama3.3:70b", "qwen2.5:72b")
    LOLM_LOCAL_API     "ollama" (default) or "openai" (the /v1 chat-completions shape)
    LOLM_SOVEREIGN     "1" → ONLY the local brain may generate; cloud is refused
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional

from local_ui.claude_reasoner import _split_messages, telemetry_traces_from_text


def sovereign() -> bool:
    """True when the owner has cut the cloud — only on-device generation allowed."""
    return os.environ.get("LOLM_SOVEREIGN", "").strip() in ("1", "true", "yes", "on")


def _messages(req: Any) -> List[Dict[str, str]]:
    system, turns = _split_messages(req.messages)
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(turns)
    return msgs


class LocalServerReasonerLoop:
    """Generation from a local inference server, telemetered by the on-device graft.

    A drop-in twin of WorkersAIReasonerLoop: same request in, same start/token/done
    events out — but the text never leaves the machine."""

    def __init__(self, state_fn: Callable[[], Any],
                 url: Optional[str] = None,
                 model: Optional[str] = None,
                 api: Optional[str] = None,
                 timeout: float = 120.0):
        self.state_fn = state_fn
        self.url = (url or os.environ.get("LOLM_LOCAL_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("LOLM_LOCAL_MODEL", "")
        self.api = (api or os.environ.get("LOLM_LOCAL_API", "ollama")).lower()
        self.timeout = timeout
        self._healthy: Optional[bool] = None
        self._checked_at: float = 0.0

    # ── availability (cheap, cached health probe) ────────────────────────────
    def configured(self) -> bool:
        return bool(self.url and self.model)

    def available(self) -> bool:
        if not self.configured():
            return False
        now = time.time()
        if self._healthy is not None and (now - self._checked_at) < 30:
            return self._healthy
        self._checked_at = now
        try:
            probe = self.url + ("/api/tags" if self.api == "ollama" else "/v1/models")
            with urllib.request.urlopen(urllib.request.Request(probe), timeout=3) as r:
                self._healthy = (r.status == 200)
        except Exception:
            self._healthy = False
        return self._healthy

    def _endpoint_and_payload(self, req: Any) -> tuple:
        msgs = _messages(req)
        max_tok = max(int(getattr(req, "max_new_tokens", 256)) * 3, 256)
        temp = float(getattr(req, "temperature", 0.3) or 0.3)
        if self.api == "openai":
            return (self.url + "/v1/chat/completions",
                    {"model": self.model, "messages": msgs, "stream": False,
                     "max_tokens": max_tok, "temperature": temp})
        # default: Ollama native chat
        return (self.url + "/api/chat",
                {"model": self.model, "messages": msgs, "stream": False,
                 "options": {"temperature": temp, "num_predict": max_tok}})

    def _generate(self, req: Any) -> str:
        endpoint, payload = self._endpoint_and_payload(req)
        request = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "lolm-local/1.0"})
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        if self.api == "openai":
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return (data.get("message") or {}).get("content", "")

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        started = time.perf_counter()
        if not self.configured():
            yield {"event": "error", "data": {"error": "local brain not configured "
                   "(set LOLM_LOCAL_MODEL, run e.g. `ollama run llama3.3:70b`)"}}
            return
        try:
            text = (self._generate(req) or "").strip()
            if not text:
                raise RuntimeError("empty local response")
        except Exception as exc:
            yield {"event": "error", "data": {"error": f"local brain failed: {exc}"[:400]}}
            return

        model_label = f"local:{self.model}"
        state = self.state_fn()
        backbone = getattr(state, "backbone", None)
        graft = getattr(state, "graft", None)
        if getattr(req, "telemeter", True):
            try:
                traces = telemetry_traces_from_text(backbone, graft, text)
            except Exception:
                traces = []
        else:
            traces = []

        yield {"event": "start", "data": {
            "profile": model_label, "use_graft": bool(traces),
            "latent_backend": "monitor" if traces else None, "reasoner": "local"}}

        # Telemetry summary comes from the graft traces; but the DISPLAYED text is the
        # REAL Ollama output (which has correct spacing). Decoding graft token-ids for
        # display loses spaces — the graft's tokenizer ≠ how the local model wrote the
        # text. So we stream the real words and ATTACH the per-token telemetry by index.
        gate_means: List[float] = [t.get("gate_mean", 0.0) for t in traces] if traces else []
        controls: List[int] = [max(range(len(t["control_logits"])), key=t["control_logits"].__getitem__)
                               for t in traces if t.get("control_logits")]
        words = text.split(" ") if text else []
        for i, w in enumerate(words):
            tr = traces[min(i, len(traces) - 1)] if traces else {"used_graft": False}
            yield {"event": "token", "data": {"token": w + " ", "trace": tr}}

        elapsed = max(time.perf_counter() - started, 1e-9)
        n_tokens = len(traces) or len(text.split(" "))
        avg_gate = sum(gate_means) / len(gate_means) if gate_means else None
        yield {"event": "done", "data": {
            "id": f"local-{int(time.time() * 1000)}", "response": text,
            "tokens": n_tokens, "profile": model_label, "reasoner": "local",
            "use_graft": bool(traces), "seconds": elapsed,
            "tok_per_sec": n_tokens / elapsed, "sovereign": True,
            "summary": {"avg_gate": avg_gate,
                        "last_control": controls[-1] if controls else None}}}


class BestBrain:
    """Brain selector: prefer the LOCAL sovereign model; fall back to the cloud brain
    only when local is unavailable AND sovereign mode is off. This is what makes
    'runs entirely on your machine' the default whenever a local model is up, while
    still working out-of-the-box on the shared demo box (cloud) for now."""

    def __init__(self, local: LocalServerReasonerLoop, cloud: Any):
        self.local = local
        self.cloud = cloud

    def active(self) -> str:
        if self.local.available():
            return "local"
        if not sovereign() and self.cloud is not None and self.cloud.available():
            return "cloud"
        return "none"

    def available(self) -> bool:
        return self.active() != "none"

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        choice = self.active()
        if choice == "local":
            yield from self.local(req)
            return
        if choice == "cloud":
            yield from self.cloud(req)
            return
        yield {"event": "error", "data": {"error": (
            "no brain available: sovereign mode is on but no local model is running "
            "(start one, e.g. `ollama run llama3.3:70b`)" if sovereign()
            else "no brain available (configure a local model or the cloud reasoner)")}}
