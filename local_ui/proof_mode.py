"""Proof Mode for LOLM-NFET.

Runs the same prompt through base generation and LOLM/NFET generation, then
returns a plain comparison so the user can see whether the graft actually
changed behavior.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List


def _clone_chat_request(req: Any, *, use_graft: bool, max_tokens: int | None = None) -> Any:
    update = {"use_graft": use_graft}
    if max_tokens is not None:
        update["max_new_tokens"] = max_tokens
    if hasattr(req, "model_copy"):
        return req.model_copy(update=update)
    data = req.dict()
    data.update(update)
    return type(req)(**data)


def _collect_generation(req: Any, generation_loop: Callable[[Any], Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    result: Dict[str, Any] | None = None
    streamed = ""
    token_events = 0
    for event in generation_loop(req):
        name = event.get("event")
        data = event.get("data", {})
        if name == "error":
            raise RuntimeError(data.get("error", "generation failed"))
        if name == "token":
            token_events += 1
            streamed += data.get("token", "")
        if name == "done":
            result = data
    elapsed = max(time.perf_counter() - start, 1e-9)
    if result is None:
        result = {"response": streamed, "tokens": token_events}
    result["elapsed_seconds"] = elapsed
    result["tokens_per_second"] = float(result.get("tokens", token_events) or token_events) / elapsed
    return result


def _summarize_difference(base: Dict[str, Any], lolm: Dict[str, Any]) -> Dict[str, Any]:
    base_text = (base.get("response") or "").strip()
    lolm_text = (lolm.get("response") or "").strip()
    base_words = set(base_text.lower().split())
    lolm_words = set(lolm_text.lower().split())
    overlap = len(base_words & lolm_words)
    union = max(len(base_words | lolm_words), 1)
    similarity = overlap / union
    summary = lolm.get("summary", {}) or {}
    return {
        "changed_text": base_text != lolm_text,
        "word_similarity": similarity,
        "base_tokens": base.get("tokens"),
        "lolm_tokens": lolm.get("tokens"),
        "base_tok_per_sec": base.get("tokens_per_second"),
        "lolm_tok_per_sec": lolm.get("tokens_per_second"),
        "avg_gate": summary.get("avg_gate"),
        "avg_latent_share": summary.get("avg_latent_share"),
        "avg_regime_entropy": summary.get("avg_regime_entropy"),
        "last_control": summary.get("last_control"),
        "plain_english": _plain_english(base_text, lolm_text, summary, similarity),
    }


def _plain_english(base_text: str, lolm_text: str, summary: Dict[str, Any], similarity: float) -> str:
    if not base_text and not lolm_text:
        return "Neither path produced useful text. This is a model/runtime failure, not a LOLM improvement."
    if base_text == lolm_text:
        return "LOLM/NFET did not visibly change the answer. The architecture ran, but the user-facing result is effectively the same."
    latent = summary.get("avg_latent_share")
    control = summary.get("last_control") or "unknown"
    if latent is None:
        return f"The answers changed, but no reliable latent-share summary was recorded. Final NFET control: {control}."
    pct = round(float(latent) * 100)
    if similarity < 0.45:
        return f"LOLM/NFET substantially changed the answer. Average latent contribution was about {pct}%, and final NFET control was {control}."
    return f"LOLM/NFET moderately changed the answer. Average latent contribution was about {pct}%, and final NFET control was {control}."


def register_proof_routes(app: Any, ChatRequest: Any, generation_loop: Callable[[Any], Any], append_improvement_event: Callable[[Dict[str, Any]], None]) -> None:
    @app.post("/api/proof/compare")
    def proof_compare(req: ChatRequest):
        max_tokens = min(int(getattr(req, "max_new_tokens", 24) or 24), 48)
        base_req = _clone_chat_request(req, use_graft=False, max_tokens=max_tokens)
        lolm_req = _clone_chat_request(req, use_graft=True, max_tokens=max_tokens)
        base = _collect_generation(base_req, generation_loop)
        lolm = _collect_generation(lolm_req, generation_loop)
        diff = _summarize_difference(base, lolm)
        event = {
            "type": "proof_compare",
            "timestamp": time.time(),
            "base_id": base.get("id"),
            "lolm_id": lolm.get("id"),
            "diff": diff,
        }
        append_improvement_event(event)
        return {"base": base, "lolm": lolm, "diff": diff}
