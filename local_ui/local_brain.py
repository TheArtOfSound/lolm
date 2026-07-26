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

When LOLM_LOCAL_* is unset, this module auto-discovers the evolved-weights server
on :11435 (`scripts/serve_evolved.py`, model `lolm-evolved`). That path is used as a
rescue after Claude / Workers fail — not ahead of a live frontier brain — so the
self-learned weights actually answer mid-dialog outages instead of the tiny 0.6B.

Env:
    LOLM_LOCAL_URL     base URL of the local server (default http://127.0.0.1:11434)
    LOLM_LOCAL_MODEL   model name to ask for (e.g. "llama3.3:70b", "qwen2.5:72b")
    LOLM_LOCAL_API     "ollama" (default) or "openai" (the /v1 chat-completions shape)
    LOLM_EVOLVED_URL   evolved serve probe URL (default http://127.0.0.1:11435)
    LOLM_SOVEREIGN     "1" → ONLY the local brain may generate; cloud is refused
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from local_ui.claude_reasoner import _split_messages, telemetry_traces_from_text

# Evolved-weights defaults (scripts/serve_evolved.py). Auto-used only when the
# owner has not pinned LOLM_LOCAL_* and the endpoint is actually live.
EVOLVED_DEFAULT_URL = "http://127.0.0.1:11435"
EVOLVED_DEFAULT_MODEL = "lolm-evolved"
EVOLVED_DEFAULT_API = "openai"
_EVOLVED_PROBE_TTL = 15.0
_evolved_probe_cache: Dict[str, Any] = {"ok": None, "at": 0.0, "url": ""}


def sovereign() -> bool:
    """True when the owner has cut the cloud — only on-device generation allowed."""
    return os.environ.get("LOLM_SOVEREIGN", "").strip() in ("1", "true", "yes", "on")


def evolved_url() -> str:
    return (os.environ.get("LOLM_EVOLVED_URL", "").strip() or EVOLVED_DEFAULT_URL).rstrip("/")


def probe_evolved(url: Optional[str] = None, *, force: bool = False) -> bool:
    """Cheap cached probe of the evolved OpenAI-compatible endpoint."""
    base = (url or evolved_url()).rstrip("/")
    now = time.time()
    if (
        not force
        and _evolved_probe_cache.get("url") == base
        and _evolved_probe_cache.get("ok") is not None
        and (now - float(_evolved_probe_cache.get("at") or 0.0)) < _EVOLVED_PROBE_TTL
    ):
        return bool(_evolved_probe_cache["ok"])
    ok = False
    try:
        with urllib.request.urlopen(
            urllib.request.Request(base + "/v1/models"), timeout=1.5
        ) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    _evolved_probe_cache["ok"] = ok
    _evolved_probe_cache["at"] = now
    _evolved_probe_cache["url"] = base
    return ok


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
    events out — but the text never leaves the machine.

    Config resolution (HOT-APPLY — re-read every call):
      1. ctor overrides (tests)
      2. explicit LOLM_LOCAL_URL / LOLM_LOCAL_MODEL / LOLM_LOCAL_API
      3. auto-discovered evolved serve on :11435 when live
    """

    def __init__(self, state_fn: Callable[[], Any],
                 url: Optional[str] = None,
                 model: Optional[str] = None,
                 api: Optional[str] = None,
                 timeout: float = 120.0):
        self.state_fn = state_fn
        # HOT-APPLY: ctor args are test overrides; url/model/api resolve from env
        # per call so a Keys-panel save applies immediately (no restart).
        self._url_override = url
        self._model_override = model
        self._api_override = api
        self.timeout = timeout
        self._healthy: Optional[bool] = None
        self._checked_at: float = 0.0
        self._health_cfg: tuple = ()

    def _explicit_env(self) -> bool:
        """True when the owner pinned local via env or ctor (not auto-evolved)."""
        if self._url_override or self._model_override or self._api_override:
            return True
        return bool(
            os.environ.get("LOLM_LOCAL_URL", "").strip()
            or os.environ.get("LOLM_LOCAL_MODEL", "").strip()
            or os.environ.get("LOLM_LOCAL_API", "").strip()
        )

    def resolve(self) -> Dict[str, str]:
        """Resolve effective url/model/api/source for this call."""
        if self._url_override or self._model_override or self._api_override:
            url = (self._url_override or os.environ.get("LOLM_LOCAL_URL", "http://127.0.0.1:11434")).rstrip("/")
            model = self._model_override or os.environ.get("LOLM_LOCAL_MODEL", "")
            api = (self._api_override or os.environ.get("LOLM_LOCAL_API", "ollama")).lower()
            if not api:
                api = "openai" if "11435" in url or model == EVOLVED_DEFAULT_MODEL else "ollama"
            return {"url": url, "model": model, "api": api, "source": "override"}

        env_url = os.environ.get("LOLM_LOCAL_URL", "").strip()
        env_model = os.environ.get("LOLM_LOCAL_MODEL", "").strip()
        env_api = os.environ.get("LOLM_LOCAL_API", "").strip().lower()
        if env_url or env_model:
            url = (env_url or "http://127.0.0.1:11434").rstrip("/")
            model = env_model
            if env_api:
                api = env_api
            elif "11435" in url or model == EVOLVED_DEFAULT_MODEL:
                api = EVOLVED_DEFAULT_API
            else:
                api = "ollama"
            return {"url": url, "model": model, "api": api, "source": "env"}

        # Auto-discover evolved weights server — rescue brain after frontier fails.
        eurl = evolved_url()
        if probe_evolved(eurl):
            return {
                "url": eurl,
                "model": EVOLVED_DEFAULT_MODEL,
                "api": EVOLVED_DEFAULT_API,
                "source": "evolved_auto",
            }
        return {
            "url": "http://127.0.0.1:11434",
            "model": "",
            "api": "ollama",
            "source": "none",
        }

    @property
    def url(self) -> str:
        return self.resolve()["url"]

    @property
    def model(self) -> str:
        return self.resolve()["model"]

    @property
    def api(self) -> str:
        return self.resolve()["api"]

    def source(self) -> str:
        return self.resolve()["source"]

    # ── availability (cheap, cached health probe) ────────────────────────────
    def configured(self) -> bool:
        cfg = self.resolve()
        return bool(cfg["url"] and cfg["model"])

    def available(self) -> bool:
        if not self.configured():
            return False
        cfg = self.resolve()
        # evolved_auto already probed live in resolve(); trust that cache.
        if cfg["source"] == "evolved_auto":
            return True
        now = time.time()
        key = (cfg["url"], cfg["model"], cfg["api"])
        if key != self._health_cfg:                 # config changed → re-probe now
            self._healthy, self._health_cfg = None, key
        if self._healthy is not None and (now - self._checked_at) < 30:
            return self._healthy
        self._checked_at = now
        try:
            probe = cfg["url"] + ("/api/tags" if cfg["api"] == "ollama" else "/v1/models")
            with urllib.request.urlopen(urllib.request.Request(probe), timeout=3) as r:
                self._healthy = (r.status == 200)
        except Exception:
            self._healthy = False
        return self._healthy

    def _endpoint_and_payload(self, req: Any) -> tuple:
        cfg = self.resolve()
        msgs = _messages(req)
        max_tok = max(int(getattr(req, "max_new_tokens", 256)) * 3, 256)
        temp = float(getattr(req, "temperature", 0.3) or 0.3)
        if cfg["api"] == "openai":
            return (cfg["url"] + "/v1/chat/completions",
                    {"model": cfg["model"], "messages": msgs, "stream": False,
                     "max_tokens": max_tok, "temperature": temp})
        # default: Ollama native chat
        return (cfg["url"] + "/api/chat",
                {"model": cfg["model"], "messages": msgs, "stream": False,
                 "options": {"temperature": temp, "num_predict": max_tok}})

    def _generate(self, req: Any) -> str:
        endpoint, payload = self._endpoint_and_payload(req)
        headers = {"Content-Type": "application/json", "User-Agent": "lolm-local/1.0"}
        # keyed OpenAI-compatible endpoints (LM Studio remote, vLLM behind auth, …)
        api_key = os.environ.get("LOLM_LOCAL_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        cfg = self.resolve()
        if cfg["api"] == "openai":
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return (data.get("message") or {}).get("content", "")

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        started = time.perf_counter()
        cfg = self.resolve()
        if not (cfg["url"] and cfg["model"]):
            yield {"event": "error", "data": {"error": "local brain not configured "
                   "(set LOLM_LOCAL_MODEL, or run `python scripts/serve_evolved.py --port 11435`)"}}
            return
        try:
            text = (self._generate(req) or "").strip()
            if not text:
                raise RuntimeError("empty local response")
        except Exception as exc:
            # Invalidate evolved probe so the next turn re-checks liveness.
            if cfg["source"] == "evolved_auto":
                _evolved_probe_cache["ok"] = False
                _evolved_probe_cache["at"] = 0.0
            yield {"event": "error", "data": {"error": f"local brain failed: {exc}"[:400]}}
            return

        model_label = f"local:{cfg['model']}"
        if cfg["source"] == "evolved_auto":
            model_label = f"evolved:{cfg['model']}"
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
            "latent_backend": "monitor" if traces else None, "reasoner": "local",
            "local_source": cfg["source"]}}

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
            "local_source": cfg["source"],
            "use_graft": bool(traces), "seconds": elapsed,
            "tok_per_sec": n_tokens / elapsed, "sovereign": True,
            "summary": {"avg_gate": avg_gate,
                        "last_control": controls[-1] if controls else None}}}


class BestBrain:
    """Brain selector with resilient mid-dialog fallthrough.

    Order of preference:
      - LOLM_SOVEREIGN / LOLM_BRAIN=local → local only (cloud refused in sovereign)
      - Explicit LOLM_LOCAL_* → local first, cloud rescue
      - Auto-discovered evolved :11435 → cloud first, evolved as rescue after
        Claude/Workers fail (never demote a live 70B to a 3B by accident)
      - Else cloud, then nothing

    Pre-token errors fall through to the next brain with an honest
    ``brain_fallback`` phase event so receipts stay truthful.
    """

    def __init__(self, local: LocalServerReasonerLoop, cloud: Any):
        self.local = local
        self.cloud = cloud

    def _cloud_ok(self) -> bool:
        return (not sovereign()) and self.cloud is not None and bool(
            getattr(self.cloud, "available", lambda: False)()
        )

    def _attempt_order(self) -> List[Tuple[str, Any]]:
        pin = os.environ.get("LOLM_BRAIN", "").lower().strip()
        local_ok = self.local.available()
        cloud_ok = self._cloud_ok()
        source = self.local.source() if local_ok else "none"

        if pin == "local" or sovereign():
            order: List[Tuple[str, Any]] = []
            if local_ok:
                order.append(("local", self.local))
            if cloud_ok and not sovereign():
                order.append(("cloud", self.cloud))
            return order
        if pin in ("70b", "workers", "cloud"):
            order = []
            if cloud_ok:
                order.append(("cloud", self.cloud))
            if local_ok:
                order.append(("local", self.local))
            return order

        # Default: explicit local config prefers on-device; auto-evolved is a
        # RESCUE after cloud (Claude already peeled off by _ClaudeFirst).
        order = []
        if local_ok and source in ("env", "override"):
            order.append(("local", self.local))
            if cloud_ok:
                order.append(("cloud", self.cloud))
            return order
        if cloud_ok:
            order.append(("cloud", self.cloud))
        if local_ok:
            order.append(("local", self.local))
        return order

    def active(self) -> str:
        order = self._attempt_order()
        return order[0][0] if order else "none"

    def available(self) -> bool:
        return self.active() != "none"

    def __call__(self, req: Any) -> Iterator[Dict[str, Any]]:
        attempts = self._attempt_order()
        if not attempts:
            yield {"event": "error", "data": {"error": (
                "no brain available: sovereign mode is on but no local model is running "
                "(start evolved serve: `python scripts/serve_evolved.py --port 11435`, "
                "or e.g. `ollama run llama3.3:70b`)" if sovereign()
                else "no brain available (configure a local model, evolved :11435, or the cloud reasoner)")}}
            return

        last_error = "generation failed"
        for idx, (label, loop) in enumerate(attempts):
            emitted_real = False
            try:
                for ev in loop(req):
                    if not emitted_real and ev.get("event") == "error":
                        last_error = (ev.get("data") or {}).get("error", f"{label} failed")
                        raise RuntimeError(last_error)
                    if ev.get("event") in ("token", "done"):
                        emitted_real = True
                    yield ev
                if emitted_real:
                    return
                # Loop finished without tokens and without error event — treat as fail.
                last_error = f"{label} produced no tokens"
            except Exception as exc:
                last_error = str(exc)[:400] or last_error
                if emitted_real:
                    raise
            # Pre-token failure → honest fallthrough to the next brain.
            if idx + 1 < len(attempts):
                nxt = attempts[idx + 1][0]
                yield {"event": "phase", "data": {
                    "phase": "brain_fallback",
                    "from": label,
                    "to": nxt,
                    "note": f"{label} failed before answering — falling back to {nxt}",
                    "error": last_error[:200],
                }}
                continue
            yield {"event": "error", "data": {"error": last_error[:400]}}
            return
