"""Chat with LOLM checkpoints — load any saved checkpoint and generate text.

Runs inference on a SEPARATE process from training so it never interrupts
the active training run. Uses CPU on the droplet or a spare TPU VM.
"""

import asyncio
import os
import re
import json
import time
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends
from auth import require_auth
from training import ssh_command, get_tpu_ips
from tpu import DEFAULT_ZONE

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_auth)])

# Chat history stored on disk
DATA_DIR = Path("/opt/lolm-dashboard/data")
DATA_DIR.mkdir(exist_ok=True)
CHAT_FILE = DATA_DIR / "chat_history.json"


def _load_chats() -> list:
    try:
        return json.loads(CHAT_FILE.read_text())
    except Exception:
        return []


def _save_chat(entry: dict):
    chats = _load_chats()
    chats.append(entry)
    if len(chats) > 200:
        chats = chats[-200:]
    CHAT_FILE.write_text(json.dumps(chats, indent=2, default=str))


@router.post("/generate")
async def generate_text(
    prompt: str = "Once upon a time",
    checkpoint: str = "",
    max_tokens: int = 100,
    temperature: float = 0.8,
    tpu_name: str = "lolm-7b",
    zone: str = DEFAULT_ZONE,
):
    """Generate text from a LOLM checkpoint WITHOUT stopping training.

    Strategy:
    1. SSH to worker 0 of the TPU VM
    2. Run a SEPARATE python process that loads the checkpoint on CPU
       (training uses TPU, inference uses CPU — no conflict)
    3. Generate tokens and return the text

    The inference script runs in a subshell, not in the training tmux session.
    """
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"error": "No TPU IPs available"}

    # Find the checkpoint to use
    if not checkpoint:
        # Use the latest checkpoint on the TPU
        rc, out, _ = await ssh_command(ips[0],
            "ls -t ~/Latent/runs/*/ckpt_*.pt 2>/dev/null | head -1",
            timeout=10,
        )
        checkpoint = out.strip()
        if not checkpoint:
            return {"error": "No checkpoints found. Training needs to save at least one checkpoint (every 500 steps)."}

    # Build the inference script — runs on CPU, separate from training
    # Escape the path for Python string
    ckpt_escaped = checkpoint.replace("'", "\\'")
    prompt_escaped = prompt.replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n')

    inference_script = f"""
import sys
sys.path.insert(0, '/home/bry/Latent')
import torch
from lolm.config import load_config
from lolm.model import LOLM
import tiktoken

# Load checkpoint on CPU (training uses TPU — no conflict)
ckpt_path = '{ckpt_escaped}'
print(f"Loading {{ckpt_path}}...", flush=True)
ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)

# Figure out which config was used
config_path = ckpt.get("config", "")
if "1b" in config_path or "1b" in ckpt_path:
    config_path = "configs/scale/1b_lolm_pod.yaml"
elif "2b" in config_path:
    config_path = "configs/scale/2b_lolm_pod.yaml"
elif "500m" in config_path:
    config_path = "configs/scale/500m_lolm_pod.yaml"
else:
    config_path = "configs/scale/1b_lolm_pod.yaml"

cfg = load_config(config_path)
model = LOLM(cfg.model)

# Fix aliased memory: re-create all parameters as fresh contiguous tensors
# This breaks the shared storage that causes "more than one element refers
# to a single memory location" during load_state_dict
for name, param in list(model.named_parameters()):
    parts = name.split('.')
    obj = model
    for p in parts[:-1]:
        if p.isdigit():
            obj = obj[int(p)]
        else:
            obj = getattr(obj, p)
    setattr(obj, parts[-1], torch.nn.Parameter(param.data.clone().contiguous(), requires_grad=param.requires_grad))

state_dict = {{k: v.clone().contiguous() for k, v in ckpt["model"].items()}}
model.load_state_dict(state_dict, strict=False)
model.eval()
step = ckpt.get("step", 0)
print(f"Model loaded from step {{step}}", flush=True)

# Tokenize
enc = tiktoken.get_encoding("gpt2")
prompt = '{prompt_escaped}'
input_ids = enc.encode(prompt)
x = torch.tensor([input_ids], dtype=torch.long)

# Generate
with torch.no_grad():
    for i in range({max_tokens}):
        out = model(x, regime_temperature=0.5)
        logits = out.logits[:, -1, :] / {temperature}
        probs = torch.softmax(logits, dim=-1)
        next_token = torch.multinomial(probs, 1)
        x = torch.cat([x, next_token], dim=1)
        # Keep context window manageable
        if x.shape[1] > cfg.model.max_seq_len:
            x = x[:, -cfg.model.max_seq_len:]

generated_ids = x[0].tolist()
text = enc.decode(generated_ids)
print("GENERATED_TEXT_START")
print(text)
print("GENERATED_TEXT_END")
print(f"STEP:{{step}}")
"""

    # Write script to temp file on TPU then execute (avoids quoting hell with -c)
    script_write_cmd = f"cat > /tmp/lolm_chat.py << 'CHATEOF'\n{inference_script}\nCHATEOF"
    await ssh_command(ips[0], script_write_cmd, timeout=10)

    # Run inference on CPU via SSH — separate from training
    rc, out, err = await ssh_command(ips[0],
        'cd ~/Latent && python3 /tmp/lolm_chat.py',
        timeout=120,  # 2 min timeout for loading + generating
    )

    # Parse the output
    generated_text = ""
    step = 0
    if "GENERATED_TEXT_START" in out:
        parts = out.split("GENERATED_TEXT_START")
        if len(parts) > 1:
            text_part = parts[1].split("GENERATED_TEXT_END")[0].strip()
            generated_text = text_part
    step_match = re.search(r'STEP:(\d+)', out)
    if step_match:
        step = int(step_match.group(1))

    if not generated_text and err:
        return {
            "error": f"Generation failed: {err[-500:]}",
            "output": out[-500:],
            "checkpoint": checkpoint,
        }

    # Save to chat history
    entry = {
        "prompt": prompt,
        "response": generated_text,
        "checkpoint": checkpoint,
        "step": step,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _save_chat(entry)

    return {
        "prompt": prompt,
        "response": generated_text,
        "step": step,
        "checkpoint": os.path.basename(checkpoint),
        "tokens_generated": len(generated_text.split()),
    }


@router.get("/history")
async def get_chat_history(limit: int = 50):
    """Get chat history."""
    chats = _load_chats()
    return {"chats": chats[-limit:]}


@router.get("/checkpoints")
async def list_chat_checkpoints(tpu_name: str = "lolm-7b", zone: str = DEFAULT_ZONE):
    """List available checkpoints for chat."""
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"checkpoints": []}

    rc, out, _ = await ssh_command(ips[0],
        "find ~/Latent/runs -name 'ckpt_*.pt' -printf '%p %s\\n' 2>/dev/null | sort -t_ -k2 -n",
        timeout=10,
    )
    checkpoints = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            path = parts[0]
            name = os.path.basename(path)
            step_match = re.search(r'ckpt_(\d+)', name)
            step = int(step_match.group(1)) if step_match else 0
            checkpoints.append({"path": path, "name": name, "step": step})

    return {"checkpoints": checkpoints}
