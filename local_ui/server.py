"""Local GPT-style chat server for LOLM-NFET.

Run from repo root:
    python local_ui/server.py
    open http://localhost:7860

This is separate from the TPU dashboard. It is for local hosting: load a HF
checkpoint, optionally attach a LOLM-NFET graft, and chat through a browser UI.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import torch.nn.functional as F
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"

import sys
sys.path.insert(0, str(ROOT))

from lolm.hf_backbone import FrozenHFBackbone
from lolm.hf_lm_head import project_with_backbone_lm_head
from lolm.hf_registry import HFRegistry
from lolm.nfet_graft import LOLMNFETGraft


class LoadRequest(BaseModel):
    profile: str = "qwen3_0_6b_smoke"
    registry: str = "configs/hf_models.yaml"
    device: str = "auto"
    use_graft: bool = True
    graft_checkpoint: Optional[str] = None
    latent_backend: str = "selective_ssm"


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


@dataclass
class RuntimeState:
    backbone: Optional[FrozenHFBackbone] = None
    graft: Optional[LOLMNFETGraft] = None
    profile: Optional[str] = None
    device: Optional[torch.device] = None
    use_graft: bool = True
    loaded_at: float = 0.0
    history: List[Dict[str, Any]] = field(default_factory=list)


STATE = RuntimeState()
app = FastAPI(title="LOLM-NFET Local Workspace", version="0.1.0")
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
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    if name in {"none", "device_map"}:
        return None
    return torch.device(name)


def render_prompt(messages: List[ChatMessage]) -> str:
    parts = []
    system_seen = False
    for msg in messages:
        role = msg.role.strip().lower()
        content = msg.content.strip()
        if not content:
            continue
        if role == "system":
            system_seen = True
            parts.append(f"System: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        else:
            parts.append(f"User: {content}")
    if not system_seen:
        parts.insert(0, "System: You are LOLM-NFET, a local research assistant. Be precise, direct, and honest about uncertainty.")
    parts.append("Assistant:")
    return "\n".join(parts)


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


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"))


@app.get("/api/status")
def status():
    return {
        "loaded": STATE.backbone is not None,
        "profile": STATE.profile,
        "device": str(STATE.device) if STATE.device else None,
        "use_graft": STATE.use_graft,
        "loaded_at": STATE.loaded_at,
        "history_count": len(STATE.history),
    }


@app.get("/api/profiles")
def profiles():
    registry = HFRegistry.load(ROOT / "configs/hf_models.yaml")
    return {"profiles": [p.__dict__ for p in registry.iter_profiles()]}


@app.post("/api/load")
def load_model(req: LoadRequest):
    device = pick_device(req.device)
    backbone = FrozenHFBackbone.from_registry(req.profile, str(ROOT / req.registry), freeze=True)
    if device is not None:
        try:
            backbone.to(device)
        except RuntimeError as exc:
            return {"warning": f"model loaded, but device move failed: {exc}", "profile": req.profile}
    graft = None
    if req.use_graft:
        graft = LOLMNFETGraft(d_model=backbone.hidden_size, latent_backend=req.latent_backend)  # type: ignore[arg-type]
        if req.graft_checkpoint:
            ckpt = torch.load(req.graft_checkpoint, map_location="cpu")
            graft.load_state_dict(ckpt["graft"])
        if device is not None:
            graft.to(device)
        graft.eval()
    STATE.backbone = backbone
    STATE.graft = graft
    STATE.profile = req.profile
    STATE.device = device
    STATE.use_graft = req.use_graft
    STATE.loaded_at = time.time()
    return {"loaded": True, "profile": req.profile, "hidden_size": backbone.hidden_size, "device": str(device)}


@app.post("/api/chat")
def chat(req: ChatRequest):
    if STATE.backbone is None:
        raise HTTPException(status_code=400, detail="No model loaded. Load a profile first.")
    backbone = STATE.backbone
    graft = STATE.graft if req.use_graft and STATE.graft is not None else None
    prompt = render_prompt(req.messages)
    batch = backbone.tokenizer(prompt, return_tensors="pt")
    if STATE.device is not None:
        batch = {k: v.to(STATE.device) for k, v in batch.items()}
    input_ids = batch["input_ids"]
    start_len = input_ids.size(1)
    gate_means: List[float] = []
    regimes: List[float] = []
    controls: List[int] = []

    with torch.no_grad():
        for _ in range(req.max_new_tokens):
            base = backbone(input_ids=input_ids)
            if graft is not None:
                gout = graft(base.hidden_states, base_logits=base.logits, ablation_mode=req.ablation_mode)  # type: ignore[arg-type]
                logits = project_with_backbone_lm_head(backbone.model, gout.corrected_hidden)
                gate_means.append(float(gout.gate.mean().detach().cpu()))
                regimes.append(float(gout.nfet_state.regime_entropy.mean().detach().cpu()))
                controls.extend(gout.nfet_state.control_logits.argmax(dim=-1).detach().cpu().tolist())
            else:
                logits = base.logits
            next_token = sample_next(logits[:, -1, :], req.temperature, req.top_p)
            input_ids = torch.cat([input_ids, next_token], dim=1)
            eos = getattr(backbone.tokenizer, "eos_token_id", None)
            if eos is not None and int(next_token[0, 0].detach().cpu()) == int(eos):
                break

    generated = input_ids[0, start_len:].detach().cpu().tolist()
    text = backbone.tokenizer.decode(generated, skip_special_tokens=True)
    entry = {
        "prompt": prompt,
        "response": text,
        "profile": STATE.profile,
        "use_graft": graft is not None,
        "ablation_mode": req.ablation_mode,
        "tokens": len(generated),
        "timestamp": time.time(),
    }
    STATE.history.append(entry)
    STATE.history = STATE.history[-200:]
    return {
        "response": text,
        "tokens": len(generated),
        "profile": STATE.profile,
        "use_graft": graft is not None,
        "nfet": {
            "gate_mean": sum(gate_means) / len(gate_means) if gate_means else None,
            "regime_entropy": sum(regimes) / len(regimes) if regimes else None,
            "last_control": controls[-1] if controls else None,
        },
    }


@app.get("/api/history")
def history():
    return {"history": STATE.history[-100:]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7860)
