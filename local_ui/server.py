"""Local GPT-style chat server for LOLM-NFET."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import torch
import torch.nn.functional as F
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(os.environ.get("LOCAL_UI_DATA_DIR", str(ROOT / "local_ui" / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
IMPROVEMENT_LOG = DATA_DIR / "improvement_log.jsonl"
LOCAL_MAX_PARAMS = int(os.environ.get("LOCAL_UI_MAX_PARAMS", "10000000000"))
ENABLE_MPS_AUTO = os.environ.get("LOCAL_UI_ENABLE_MPS", "0") == "1"
ALLOW_LIVE_SELECTIVE_SSM = os.environ.get("LOCAL_UI_ALLOW_SELECTIVE_SSM", "0") == "1"
CONTROL_LABELS = {0: "continue", 1: "retrieve", 2: "verify", 3: "branch", 4: "finalize"}

import sys
sys.path.insert(0, str(ROOT))

from local_ui.auto_context import build_auto_context
from local_ui.memory_store import MemoryStore
from lolm.hf_backbone import FrozenHFBackbone
from lolm.hf_lm_head import project_with_backbone_lm_head
from lolm.hf_registry import HFRegistry
from lolm.nfet_graft import LOLMNFETGraft


MEMORY = MemoryStore(DATA_DIR)


class LoadRequest(BaseModel):
    profile: str = "qwen3_0_6b_smoke"
    registry: str = "configs/hf_models.yaml"
    device: str = "auto"
    use_graft: bool = True
    graft_checkpoint: Optional[str] = None
    latent_backend: str = "gru_debug"
    allow_large: bool = False


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    max_new_tokens: int = 96
    temperature: float = 0.8
    top_p: float = 0.95
    use_graft: bool = True
    ablation_mode: str = "full"


class FeedbackRequest(BaseModel):
    entry_id: str
    rating: str
    note: str = ""


class MemoryNoteRequest(BaseModel):
    text: str
    tag: str = "note"
    importance: int = 3


class IdentityLineRequest(BaseModel):
    line: str


class GoalRequest(BaseModel):
    title: str
    why: str = ""
    priority: int = 3


class JournalRequest(BaseModel):
    markdown: str


@dataclass
class RuntimeState:
    backbone: Optional[FrozenHFBackbone] = None
    graft: Optional[LOLMNFETGraft] = None
    profile: Optional[str] = None
    device: Optional[torch.device] = None
    use_graft: bool = True
    latent_backend: Optional[str] = None
    requested_latent_backend: Optional[str] = None
    loaded_at: float = 0.0
    head_trained: bool = False
    history: List[Dict[str, Any]] = field(default_factory=list)


STATE = RuntimeState()
app = FastAPI(title="LOLM-NFET Local Workspace", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def pick_device(name: str) -> Optional[torch.device]:
    if name == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if ENABLE_MPS_AUTO and hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    if name in {"none", "device_map"}:
        return None
    return torch.device(name)


def live_safe_backend(requested: str) -> tuple[str, Optional[str]]:
    if requested == "selective_ssm" and not ALLOW_LIVE_SELECTIVE_SSM:
        return "gru_debug", "selective_ssm is disabled for live local chat; using gru_debug visualizer. Set LOCAL_UI_ALLOW_SELECTIVE_SSM=1 to opt in."
    return requested, None


def build_graft(d_model: int, backend: str, device: Optional[torch.device]) -> LOLMNFETGraft:
    graft = LOLMNFETGraft(d_model=d_model, latent_backend=backend)  # type: ignore[arg-type]
    if device is not None:
        graft.to(device)
    graft.eval()
    return graft


def graft_param(graft: LOLMNFETGraft) -> torch.nn.Parameter:
    return next(graft.parameters())


def cast_for_graft(hidden: torch.Tensor, logits: torch.Tensor, graft: LOLMNFETGraft) -> tuple[torch.Tensor, torch.Tensor]:
    param = graft_param(graft)
    return hidden.to(device=param.device, dtype=param.dtype), logits.to(device=param.device, dtype=param.dtype)


def ensure_live_safe_graft(backbone: FrozenHFBackbone) -> Optional[str]:
    if STATE.graft is None:
        return None
    backend = getattr(STATE.graft, "latent_backend", STATE.latent_backend)
    if backend == "selective_ssm" and not ALLOW_LIVE_SELECTIVE_SSM:
        STATE.graft = build_graft(backbone.hidden_size, "gru_debug", STATE.device)
        STATE.latent_backend = "gru_debug"
        return "Existing selective_ssm graft was replaced with gru_debug for live-chat stability."
    return None


def normalized_chat_messages(messages: List[ChatMessage]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    has_system = False
    for msg in messages:
        role = msg.role.strip().lower()
        content = msg.content.strip()
        if not content:
            continue
        if role not in {"system", "user", "assistant"}:
            role = "user"
        if role == "system":
            has_system = True
        out.append({"role": role, "content": content})
    base_system = "You are LOLM-NFET, a local assistant. Answer directly. Do not reveal hidden reasoning or narrate your thought process. Use the AUTO_CONTEXT as private operating context, not as text to repeat."
    auto = build_auto_context(DATA_DIR)
    if has_system:
        out.insert(1, {"role": "system", "content": auto})
    else:
        out.insert(0, {"role": "system", "content": base_system})
        out.insert(1, {"role": "system", "content": auto})
    return out


def render_prompt_fallback(messages: List[Dict[str, str]]) -> str:
    parts = []
    for msg in messages:
        parts.append(f"{msg['role'].capitalize()}: {msg['content']}")
    parts.append("Assistant:")
    return "\n".join(parts)


def prepare_chat_inputs(backbone: FrozenHFBackbone, messages: List[ChatMessage], device: Optional[torch.device]) -> Dict[str, torch.Tensor]:
    chat_messages = normalized_chat_messages(messages)
    tokenizer = backbone.tokenizer
    try:
        batch = tokenizer.apply_chat_template(chat_messages, add_generation_prompt=True, tokenize=True, return_tensors="pt", enable_thinking=False)
        if isinstance(batch, torch.Tensor):
            batch = {"input_ids": batch}
    except TypeError:
        try:
            batch = tokenizer.apply_chat_template(chat_messages, add_generation_prompt=True, tokenize=True, return_tensors="pt")
            if isinstance(batch, torch.Tensor):
                batch = {"input_ids": batch}
        except Exception:
            batch = tokenizer(render_prompt_fallback(chat_messages), return_tensors="pt")
    except Exception:
        batch = tokenizer(render_prompt_fallback(chat_messages), return_tensors="pt")
    if device is not None:
        batch = {key: value.to(device) for key, value in batch.items()}
    return batch


def clean_response_text(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"(?is)^\s*(okay|alright|let me|i need to|the user).*?(?=\n\n|$)", "", text).strip()
    return text.strip()


def prompt_for_log(messages: List[ChatMessage]) -> str:
    return render_prompt_fallback(normalized_chat_messages(messages))


def sample_next(logits: torch.Tensor, temperature: float, top_p: float) -> torch.Tensor:
    logits = logits / max(temperature, 1e-5)
    probs = F.softmax(logits, dim=-1)
    if top_p < 1.0:
        sorted_probs, sorted_idx = torch.sort(probs, descending=True, dim=-1)
        cumulative = torch.cumsum(sorted_probs, dim=-1)
        mask = cumulative > top_p
        mask[..., 1:] = mask[..., :-1].clone()
        mask[..., 0] = False
        sorted_probs = sorted_probs.masked_fill(mask, 0.0)
        sorted_probs = sorted_probs / sorted_probs.sum(dim=-1, keepdim=True).clamp_min(1e-8)
        next_sorted = torch.multinomial(sorted_probs, num_samples=1)
        return sorted_idx.gather(-1, next_sorted)
    return torch.multinomial(probs, num_samples=1)


def entropy_from_logits(logits: torch.Tensor) -> float:
    logits = logits.float()
    log_probs = F.log_softmax(logits, dim=-1)
    probs = log_probs.exp()
    return float((-(probs * log_probs).sum(dim=-1)).detach().float().cpu().item())


def top_token(backbone: FrozenHFBackbone, logits: torch.Tensor) -> Dict[str, Any]:
    idx = int(torch.argmax(logits, dim=-1).detach().cpu().item())
    return {"id": idx, "text": backbone.tokenizer.decode([idx])}


def append_improvement_event(entry: Dict[str, Any]) -> None:
    with IMPROVEMENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def generation_loop(req: ChatRequest) -> Iterator[Dict[str, Any]]:
    if STATE.backbone is None:
        yield {"event": "error", "data": {"error": "No model loaded. Click Load model first."}}
        return
    backbone = STATE.backbone
    fallback_note = ensure_live_safe_graft(backbone)
    graft = STATE.graft if req.use_graft and STATE.graft is not None else None
    prompt = prompt_for_log(req.messages)
    batch = prepare_chat_inputs(backbone, req.messages, STATE.device)
    input_ids = batch["input_ids"]
    attention_mask = batch.get("attention_mask")
    if attention_mask is None:
        attention_mask = torch.ones_like(input_ids)
    start_len = input_ids.size(1)
    gate_means: List[float] = []
    regimes: List[float] = []
    controls: List[int] = []
    trace: List[Dict[str, Any]] = []
    last_graft_error: Optional[str] = None
    past_key_values: Any = None
    next_input_ids = input_ids
    prev_corrected: Optional[torch.Tensor] = None
    prev_drift = 0.0

    yield {"event": "start", "data": {"profile": STATE.profile, "use_graft": graft is not None, "latent_backend": STATE.latent_backend, "fallback_note": fallback_note, "fast_mode": True}}
    with torch.no_grad():
        for step in range(req.max_new_tokens):
            base = backbone(input_ids=next_input_ids, attention_mask=attention_mask, past_key_values=past_key_values, use_cache=True)
            past_key_values = base.past_key_values
            base_next_logits = base.logits[:, -1, :]
            logits = base.logits[:, -1:, :]
            token_trace: Dict[str, Any] = {"step": step + 1, "base_entropy": entropy_from_logits(base_next_logits), "base_top": top_token(backbone, base_next_logits), "used_graft": graft is not None, "latent_backend": STATE.latent_backend, "fast_mode": True}
            if graft is not None:
                try:
                    last_hidden = base.hidden_states[:, -1:, :]
                    last_logits = base.logits[:, -1:, :]
                    graft_hidden, graft_logits = cast_for_graft(last_hidden, last_logits, graft)
                    drift_feature = torch.full((graft_hidden.size(0),), prev_drift, device=graft_hidden.device, dtype=graft_hidden.dtype)
                    gout = graft(graft_hidden, base_logits=graft_logits, ablation_mode=req.ablation_mode, drift_override=drift_feature)  # type: ignore[arg-type]
                    logits = project_with_backbone_lm_head(backbone.model, gout.corrected_hidden)
                    graft_next_logits = logits[:, -1, :]
                    gate_value = float(gout.gate.mean().detach().cpu())
                    regime_value = float(gout.nfet_state.regime_entropy.mean().detach().cpu())
                    # Real lag-1 drift across streamed tokens (in-sequence drift is
                    # undefined at T=1; the controller sees the previous step's value).
                    corrected_last = gout.corrected_hidden[:, -1, :].detach()
                    if prev_corrected is not None:
                        drift_value = float((corrected_last.float() - prev_corrected.float()).pow(2).mean().cpu().item())
                    else:
                        drift_value = 0.0
                    prev_corrected = corrected_last
                    prev_drift = drift_value
                    control_logits_row = [round(float(x), 4) for x in gout.nfet_state.control_logits[0].detach().float().cpu().tolist()]
                    control_id = int(gout.nfet_state.control_logits.argmax(dim=-1)[0].detach().cpu().item())
                    gate_means.append(gate_value)
                    regimes.append(regime_value)
                    controls.append(control_id)
                    token_trace.update({"used_graft": True, "gate_mean": gate_value, "surface_share": gate_value, "latent_share": 1.0 - gate_value, "regime_entropy": regime_value, "hidden_drift": drift_value, "control_id": control_id, "control": CONTROL_LABELS.get(control_id, str(control_id)), "control_logits": control_logits_row, "graft_entropy": entropy_from_logits(graft_next_logits), "graft_top": top_token(backbone, graft_next_logits), "base_graft_delta_l2": float((graft_next_logits.float() - base_next_logits.to(graft_next_logits.device).float()).pow(2).mean().sqrt().detach().cpu().item())})
                except Exception as exc:
                    last_graft_error = str(exc)[:500]
                    token_trace.update({"used_graft": False, "graft_error": last_graft_error})
                    graft = None
                    STATE.graft = None
                    STATE.latent_backend = None
            next_token = sample_next(logits[:, -1, :], req.temperature, req.top_p)
            token_id = int(next_token[0, 0].detach().cpu().item())
            token_text = backbone.tokenizer.decode([token_id])
            token_trace["sampled"] = {"id": token_id, "text": token_text}
            trace.append(token_trace)
            yield {"event": "token", "data": {"token": token_text, "token_id": token_id, "trace": token_trace, "nfet": {"gate_mean": token_trace.get("gate_mean"), "latent_share": token_trace.get("latent_share"), "regime_entropy": token_trace.get("regime_entropy"), "hidden_drift": token_trace.get("hidden_drift"), "control": token_trace.get("control"), "base_graft_delta_l2": token_trace.get("base_graft_delta_l2")}}}
            input_ids = torch.cat([input_ids.to(next_token.device), next_token], dim=1)
            pad = torch.ones((attention_mask.size(0), 1), dtype=attention_mask.dtype, device=attention_mask.device)
            attention_mask = torch.cat([attention_mask, pad], dim=1)
            next_input_ids = next_token
            eos = getattr(backbone.tokenizer, "eos_token_id", None)
            if eos is not None and token_id == int(eos):
                break

    generated = input_ids[0, start_len:].detach().cpu().tolist()
    text = clean_response_text(backbone.tokenizer.decode(generated, skip_special_tokens=True))
    entry_id = f"chat-{int(time.time() * 1000)}"
    avg_gate = sum(gate_means) / len(gate_means) if gate_means else None
    avg_regime = sum(regimes) / len(regimes) if regimes else None
    entry = {"id": entry_id, "prompt": prompt, "response": text, "profile": STATE.profile, "use_graft": graft is not None, "ablation_mode": req.ablation_mode, "tokens": len(generated), "timestamp": time.time(), "trace": trace, "fallback_note": fallback_note, "last_graft_error": last_graft_error, "summary": {"avg_gate": avg_gate, "avg_surface_share": avg_gate, "avg_latent_share": 1.0 - avg_gate if avg_gate is not None else None, "avg_regime_entropy": avg_regime, "last_control": CONTROL_LABELS.get(controls[-1], str(controls[-1])) if controls else None}}
    STATE.history.append(entry)
    STATE.history = STATE.history[-200:]
    append_improvement_event({"type": "chat", **entry})
    yield {"event": "done", "data": {"id": entry_id, "response": text, "tokens": len(generated), "profile": STATE.profile, "use_graft": graft is not None, "latent_backend": STATE.latent_backend, "fallback_note": fallback_note, "last_graft_error": last_graft_error, "trace": trace, "summary": entry["summary"], "nfet": {"gate_mean": avg_gate, "regime_entropy": avg_regime, "last_control": controls[-1] if controls else None, "last_control_label": CONTROL_LABELS.get(controls[-1], str(controls[-1])) if controls else None}, "fast_mode": True}}


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"))


@app.get("/api/status")
def status():
    return {"loaded": STATE.backbone is not None, "profile": STATE.profile, "device": str(STATE.device) if STATE.device else None, "use_graft": STATE.use_graft, "latent_backend": STATE.latent_backend, "requested_latent_backend": STATE.requested_latent_backend, "loaded_at": STATE.loaded_at, "head_trained": STATE.head_trained, "history_count": len(STATE.history), "local_max_params": LOCAL_MAX_PARAMS, "mps_auto_enabled": ENABLE_MPS_AUTO, "live_selective_ssm_enabled": ALLOW_LIVE_SELECTIVE_SSM, "improvement_log": str(IMPROVEMENT_LOG)}


@app.get("/api/profiles")
def profiles():
    registry = HFRegistry.load(ROOT / "configs/hf_models.yaml")
    items = []
    for p in registry.iter_profiles():
        row = p.__dict__.copy()
        row["local_safe"] = p.approximate_parameters <= LOCAL_MAX_PARAMS and p.role != "teacher"
        row["size_b"] = round(p.approximate_parameters / 1_000_000_000, 2)
        items.append(row)
    return {"profiles": items, "local_max_params": LOCAL_MAX_PARAMS}


@app.post("/api/load")
def load_model(req: LoadRequest):
    registry = HFRegistry.load(ROOT / req.registry)
    profile = registry.get(req.profile)
    if not req.allow_large and (profile.role == "teacher" or profile.approximate_parameters > LOCAL_MAX_PARAMS):
        raise HTTPException(status_code=400, detail=f"Refusing local load of {profile.name} ({profile.approximate_parameters:,} params, role={profile.role}). Use qwen3_0_6b_smoke or qwen3_4b_lab locally.")
    device = pick_device(req.device)
    backend, fallback_reason = live_safe_backend(req.latent_backend)
    backbone = FrozenHFBackbone.from_registry(req.profile, str(ROOT / req.registry), freeze=True)
    if device is not None:
        try:
            backbone.to(device)
        except RuntimeError as exc:
            return {"warning": f"model loaded, but device move failed: {exc}", "profile": req.profile}
    graft = None
    head_trained = False
    if req.use_graft:
        graft = build_graft(backbone.hidden_size, backend, device)
        if req.graft_checkpoint:
            ckpt = torch.load(req.graft_checkpoint, map_location="cpu")
            graft.load_state_dict(ckpt["graft"])
            head_trained = bool(ckpt.get("head_trained", False))
    STATE.backbone = backbone
    STATE.graft = graft
    STATE.profile = req.profile
    STATE.device = device
    STATE.use_graft = req.use_graft
    STATE.latent_backend = backend if graft is not None else None
    STATE.requested_latent_backend = req.latent_backend
    STATE.loaded_at = time.time()
    STATE.head_trained = head_trained
    return {"loaded": True, "profile": req.profile, "hidden_size": backbone.hidden_size, "device": str(device), "size_b": round(profile.approximate_parameters / 1_000_000_000, 2), "latent_backend": STATE.latent_backend, "requested_latent_backend": req.latent_backend, "head_trained": head_trained, "fallback_reason": fallback_reason}


@app.post("/api/chat")
def chat(req: ChatRequest):
    result = None
    for item in generation_loop(req):
        if item["event"] == "error":
            raise HTTPException(status_code=400, detail=item["data"].get("error", "Chat failed"))
        if item["event"] == "done":
            result = item["data"]
    if result is None:
        raise HTTPException(status_code=500, detail="Generation produced no result")
    return result


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    def events() -> Iterator[str]:
        for item in generation_loop(req):
            yield sse(item["event"], item["data"])
    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    target = None
    for item in reversed(STATE.history):
        if item.get("id") == req.entry_id:
            target = item
            break
    event = {"type": "feedback", "entry_id": req.entry_id, "rating": req.rating, "note": req.note, "timestamp": time.time(), "profile": STATE.profile, "target_found": target is not None}
    append_improvement_event(event)
    return {"saved": True, "event": event, "log": str(IMPROVEMENT_LOG)}


@app.post("/api/memory/note")
def save_memory_note(req: MemoryNoteRequest):
    item_id = MEMORY.append_note(req.text, tag=req.tag, importance=req.importance)
    return {"saved": True, "id": item_id}


@app.get("/api/memory/recent")
def recent_memory(limit: int = 8):
    return {"items": MEMORY.recent_notes(limit=limit)}


@app.get("/api/memory/search")
def search_memory(q: str, limit: int = 12):
    return {"items": MEMORY.search_notes(q, limit=limit)}


@app.get("/api/memory/identity")
def get_identity():
    return {"identity": MEMORY.read_identity()}


@app.post("/api/memory/identity-line")
def add_identity_line(req: IdentityLineRequest):
    MEMORY.append_identity_line(req.line)
    return {"saved": True, "identity": MEMORY.read_identity()}


@app.get("/api/goals")
def get_goals():
    return {"items": MEMORY.get_goals()}


@app.post("/api/goals")
def add_goal(req: GoalRequest):
    item_id = MEMORY.add_goal(req.title, why=req.why, priority=req.priority)
    return {"saved": True, "id": item_id, "items": MEMORY.get_goals()}


@app.get("/api/journal")
def get_journal(max_chars: int = 8000):
    return {"journal": MEMORY.read_journal(max_chars=max_chars)}


@app.post("/api/journal")
def add_journal(req: JournalRequest):
    MEMORY.append_journal(req.markdown)
    return {"saved": True, "journal": MEMORY.read_journal()}


@app.get("/api/history")
def history():
    return {"history": STATE.history[-100:]}


@app.get("/api/improvement-log")
def improvement_log(limit: int = 50):
    if not IMPROVEMENT_LOG.exists():
        return {"items": [], "path": str(IMPROVEMENT_LOG)}
    lines = IMPROVEMENT_LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    return {"items": [json.loads(line) for line in lines if line.strip()], "path": str(IMPROVEMENT_LOG)}


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host=host, port=port)
