# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Direct BYOK providers — YOUR OWN Groq / Cerebras / OpenAI / Together /
OpenRouter key works without any gateway.

Before this module, those keys only did anything as *Cloudflare worker secrets*
(the owner's shared 70B gateway); a local sovereign user's own key was dead. This
is a drop-in twin of WorkersAIReasonerLoop that calls each provider's
OpenAI-compatible /chat/completions endpoint directly with urllib:

  - __call__      same start/token/done event protocol (graft-telemetered)
  - stream_text   SSE token deltas (same parsing as the worker passthrough)
  - generate_many best-of-N fan-out ACROSS your configured providers in
                  parallel threads — the ensemble works on your own keys

Availability is computed LIVE from env on every call (keys saved in the Keys
panel apply instantly). LOLM_SOVEREIGN=1 refuses all of it: direct calls leave
the machine, and sovereign means sovereign.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional

from local_ui.claude_reasoner import _split_messages, telemetry_traces_from_text

# Ordered fast-first. `model` is the default; <NAME>_MODEL env overrides it.
PROVIDERS: List[Dict[str, str]] = [
    {"name": "groq", "key_env": "GROQ_API_KEY", "model_env": "GROQ_MODEL",
     "url": "https://api.groq.com/openai/v1/chat/completions",
     "model": "llama-3.3-70b-versatile"},
    {"name": "cerebras", "key_env": "CEREBRAS_API_KEY", "model_env": "CEREBRAS_MODEL",
     "url": "https://api.cerebras.ai/v1/chat/completions",
     "model": "zai-glm-4.7"},
    {"name": "openai", "key_env": "OPENAI_API_KEY", "model_env": "OPENAI_MODEL",
     "url": "https://api.openai.com/v1/chat/completions",
     "model": "gpt-5.2"},
    {"name": "together", "key_env": "TOGETHER_API_KEY", "model_env": "TOGETHER_MODEL",
     "url": "https://api.together.xyz/v1/chat/completions",
     "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"},
    {"name": "openrouter", "key_env": "OPENROUTER_API_KEY", "model_env": "OPENROUTER_MODEL",
     "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": "meta-llama/llama-3.3-70b-instruct:free"},
]

# The visual-ensemble cascade ids → which direct provider can serve them, so
# generate_many honors the same ROUND1 lineup on a user's own keys.
_CASCADE_TO_PROVIDER = {
    "zai-glm-4.7": ("cerebras", "zai-glm-4.7"),
    "gpt-oss-120b": ("cerebras", "gpt-oss-120b"),
    "openai/gpt-oss-120b": ("groq", "openai/gpt-oss-120b"),
    "meta-llama/llama-4-scout-17b-16e-instruct": ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "llama-3.3-70b-versatile": ("groq", "llama-3.3-70b-versatile"),
}


def _sovereign() -> bool:
    return bool(os.environ.get("LOLM_SOVEREIGN"))


def configured() -> List[Dict[str, str]]:
    """Providers whose key is set RIGHT NOW (live env — hot-apply friendly)."""
    if _sovereign():
        return []
    return [p for p in PROVIDERS if os.environ.get(p["key_env"], "").strip()]


def _model_for(p: Dict[str, str]) -> str:
    return os.environ.get(p["model_env"], "").strip() or p["model"]


def _messages_from_req(req: Any) -> List[Dict[str, str]]:
    system, turns = _split_messages(req.messages)
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(turns)
    return msgs


def _post(url: str, key: str, payload: Dict[str, Any], timeout: float):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "User-Agent": "lolm-nfet-origin/1.0"})
    return urllib.request.urlopen(request, timeout=timeout)


def _chat_once(p: Dict[str, str], model: str, messages: List[Dict[str, str]],
               max_tokens: int, timeout: float) -> str:
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "stream": False}
    with _post(p["url"], os.environ.get(p["key_env"], ""), payload, timeout) as resp:
        j = json.loads(resp.read())
    ch = j.get("choices") or []
    return ((ch[0] or {}).get("message") or {}).get("content") or "" if ch else ""


class DirectProviderLoop:
    """Generation loop over the user's OWN provider keys — no gateway needed.
    Same event protocol as WorkersAIReasonerLoop so it drops into every flow."""

    def __init__(self, state_fn: Callable[[], Any], timeout: float = 30.0):
        self.state_fn = state_fn
        self.timeout = timeout

    def available(self) -> bool:
        return bool(configured())

    def active_provider(self) -> Optional[str]:
        c = configured()
        return c[0]["name"] if c else None

    def _n_tokens(self, req: Any) -> int:
        want = int(getattr(req, "max_new_tokens", 128))
        return min(max(want * 3, 96), 8192)

    def _generate(self, req: Any) -> Dict[str, Any]:
        """First configured provider answers; the rest are fallbacks."""
        msgs = _messages_from_req(req)
        n = self._n_tokens(req)
        errors: List[str] = []
        for p in configured():
            model = _model_for(p)
            t0 = time.time()
            try:
                text = _chat_once(p, model, msgs, n,
                                  min(self.timeout + n / 40.0, 150.0))
                if text.strip():
                    return {"text": text, "provider": f"{p['name']}-direct",
                            "model": model, "ms": int((time.time() - t0) * 1000)}
                errors.append(f"{p['name']}: empty")
            except Exception as exc:
                errors.append(f"{p['name']}: {str(exc)[:80]}")
        return {"error": "; ".join(errors) or "no direct provider configured"}

    def stream_text(self, req: Any) -> Iterator[str]:
        """SSE token deltas from the first configured provider (OpenAI shape)."""
        c = configured()
        if not c:
            raise RuntimeError("no direct provider configured")
        p = c[0]
        n = self._n_tokens(req)
        payload = {"model": _model_for(p), "messages": _messages_from_req(req),
                   "max_tokens": n, "stream": True}
        with _post(p["url"], os.environ.get(p["key_env"], ""), payload,
                   min(self.timeout + n / 40.0, 150.0)) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    j = json.loads(data)
                except Exception:
                    continue
                ch = j.get("choices")
                piece = (((ch[0] or {}).get("delta") or {}).get("content") or "") if ch else ""
                if piece:
                    yield piece

    def generate_many(self, messages: List[Dict[str, str]], models: List[str],
                      max_tokens: int = 3600) -> List[Dict[str, Any]]:
        """Best-of-N across the user's OWN keys, in parallel threads. Cascade
        model ids map to the provider that serves them; ids no configured
        provider can serve are skipped honestly (never faked)."""
        conf = {p["name"]: p for p in configured()}
        if not conf:
            return []
        n = min(max(int(max_tokens), 96), 8192)
        jobs: List[tuple] = []
        for mid in list(models)[:4]:
            prov_name, model = _CASCADE_TO_PROVIDER.get(mid, (None, mid))
            if prov_name and prov_name in conf:
                jobs.append((conf[prov_name], model))
        if not jobs:                      # nothing mappable → each provider's default
            jobs = [(p, _model_for(p)) for p in list(conf.values())[:4]]

        from concurrent.futures import ThreadPoolExecutor

        def one(job):
            p, model = job
            t0 = time.time()
            try:
                text = _chat_once(p, model, list(messages), n,
                                  min(self.timeout + n / 40.0, 150.0))
                if not text.strip():
                    raise RuntimeError("empty")
                return {"model": model, "provider": f"{p['name']}-direct",
                        "text": text, "ms": int((time.time() - t0) * 1000)}
            except Exception as exc:
                return {"model": model, "provider": f"{p['name']}-direct",
                        "error": str(exc)[:140], "ms": int((time.time() - t0) * 1000)}

        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
            return list(ex.map(one, jobs))

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        started = time.perf_counter()
        if not self.available():
            yield {"event": "error", "data": {"error": "no direct provider key configured"}}
            return
        result = self._generate(req)
        text = (result.get("text") or "").strip()
        if not text:
            yield {"event": "error", "data": {"error": f"direct providers failed: {result.get('error')}"[:400]}}
            return

        provider = result.get("provider") or "direct"
        model_label = f"{provider}:{(result.get('model') or '').split('/')[-1]}"
        state = self.state_fn()
        backbone = getattr(state, "backbone", None)
        graft = getattr(state, "graft", None)
        traces = []
        if getattr(req, "telemeter", True):
            try:
                traces = telemetry_traces_from_text(backbone, graft, text)
            except Exception:
                traces = []
        yield {"event": "start", "data": {"profile": model_label, "use_graft": bool(traces),
                                          "latent_backend": "monitor" if traces else None,
                                          "reasoner": "workers_ai"}}
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
                yield {"event": "token", "data": {"token": piece,
                                                  "token_id": trace["token_id"], "trace": trace}}
        else:
            for piece in text.split(" "):
                yield {"event": "token", "data": {"token": piece + " ",
                                                  "trace": {"used_graft": False}}}
        elapsed = max(time.perf_counter() - started, 1e-9)
        n_tokens = len(traces) or len(text.split(" "))
        avg_gate = sum(gate_means) / len(gate_means) if gate_means else None
        avg_regime = sum(regimes) / len(regimes) if regimes else None
        yield {"event": "done", "data": {
            "id": f"direct-{int(time.time() * 1000)}",
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
