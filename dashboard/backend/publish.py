"""HuggingFace Model Publishing — push trained LOLM checkpoints to HF Hub."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from auth import require_auth
from training import ssh_command, get_tpu_ips, _get_active_tpu

router = APIRouter(prefix="/api/publish", tags=["publish"], dependencies=[Depends(require_auth)])

DATA_DIR = Path("/opt/lolm-dashboard/data")
PUBLISHED_FILE = DATA_DIR / "published_models.json"

HF_TOKEN = os.environ.get("HF_TOKEN", "")


def _load_published() -> list:
    try:
        return json.loads(PUBLISHED_FILE.read_text())
    except Exception:
        return []


def _save_published(models: list):
    PUBLISHED_FILE.write_text(json.dumps(models, indent=2, default=str))


MODEL_CARD_TEMPLATE = """---
license: other
license_name: lolm-community-license
license_link: https://github.com/TheArtOfSound/lolm/blob/main/LICENSE
tags:
  - lolm
  - hybrid-transformer-ssm
  - language-model
  - latent-order
datasets:
  - {dataset}
library_name: pytorch
pipeline_tag: text-generation
---

# {model_name}

A **LOLM (Latent Order Language Model)** checkpoint — a hybrid Transformer-SSM architecture that achieves {headline_result}.

## Architecture

LOLM fuses five parallel streams via learned per-dimension gating:

| Stream | Role |
|--------|------|
| Surface Decoder | Local token relationships (Transformer + RoPE) |
| Latent SSM Core | Slow latent dynamics (Mamba-style selective scan) |
| Persistent Memory | Cross-sequence state (3-bank: episodic/semantic/self) |
| Regime Layer | Discrete phase detection (Gumbel-Softmax + causal conv1d) |
| Manifestation Gate | Surface vs latent arbitration (per-dimension sigmoid) |

## Training

- **Parameters**: {params}
- **Dataset**: {dataset}
- **Training Steps**: {steps}
- **Hardware**: Google Cloud TPU v4
- **Token Loss**: {token_loss}
- **Gate Mean**: {gate_mean}

## Key Results

- 17% average training cost savings vs matched transformer baseline
- 15% perplexity improvement at 1.57B parameters (33.2 vs 39.1)
- 52% better than Pythia-410M with 26% fewer parameters
- 14,000,000x dependency inversion when latent path removed

## Usage

```python
from lolm.config import load_config
from lolm.model import LOLM
import torch

cfg = load_config("configs/scale/1b_lolm_pod.yaml")
model = LOLM(cfg.model)
ckpt = torch.load("pytorch_model.bin", map_location="cpu")
model.load_state_dict(ckpt["model"], strict=False)
model.eval()
```

## License

LOLM Community License v1.0 — free for research/education, commercial license required for entities with >$5M revenue.

## Citation

```bibtex
@article{{leonard2026lolm,
  title={{LOLM: Language Modeling Beyond the Surface with Hybrid Transformer-SSM Latent Order Fields}},
  author={{Leonard, Bryan and Leonard, Brandyn}},
  year={{2026}},
  note={{Qira LLC. Patent pending.}}
}}
```
"""


@router.get("/models")
async def list_published():
    """List published models."""
    return {"models": _load_published()}


@router.post("/generate-card")
async def generate_model_card(
    model_name: str = "qira-llc/lolm-0.87b-fineweb-v1",
    checkpoint: str = "",
    params: str = "865M",
    dataset: str = "FineWeb-Edu",
    steps: str = "50000",
    token_loss: str = "5.32",
    gate_mean: str = "0.81",
    headline_result: str = "17% training cost savings vs matched transformers",
):
    """Generate a model card for HuggingFace."""
    card = MODEL_CARD_TEMPLATE.format(
        model_name=model_name,
        params=params,
        dataset=dataset,
        steps=steps,
        token_loss=token_loss,
        gate_mean=gate_mean,
        headline_result=headline_result,
    )
    return {"card": card, "model_name": model_name}


@router.post("/push")
async def publish_to_hf(
    model_name: str = "qira-llc/lolm-0.87b-fineweb-v1",
    checkpoint: str = "",
    tpu_name: str = "",
    zone: str = "us-central2-b",
    params: str = "865M",
    dataset: str = "FineWeb-Edu",
    steps: str = "50000",
    token_loss: str = "5.32",
    gate_mean: str = "0.81",
):
    """Publish a checkpoint to HuggingFace Hub."""
    if not HF_TOKEN:
        return {"error": "HF_TOKEN not set. Add it to ecosystem.config.js env vars."}

    name = tpu_name or _get_active_tpu()
    ips = await get_tpu_ips(name, zone)
    if not ips:
        return {"error": "No TPU available for checkpoint access"}

    # Find checkpoint
    if not checkpoint:
        rc, out, _ = await ssh_command(ips[0],
            "ls -t ~/Latent/runs/*/ckpt_*.pt 2>/dev/null | head -1", timeout=10)
        checkpoint = out.strip()
        if not checkpoint:
            return {"error": "No checkpoint found"}

    # Generate model card
    card = MODEL_CARD_TEMPLATE.format(
        model_name=model_name, params=params, dataset=dataset,
        steps=steps, token_loss=token_loss, gate_mean=gate_mean,
        headline_result="17% training cost savings vs matched transformers",
    )

    # Write model card to temp file on server, then SCP + run on TPU
    card_escaped = card.replace("'", "'\"'\"'")
    publish_cmds = [
        f"pip install huggingface_hub 2>/dev/null",
        f"export HF_TOKEN='{HF_TOKEN}'",
        f"python3 -c \"from huggingface_hub import HfApi, create_repo; "
        f"create_repo('{model_name}', private=False, exist_ok=True, token='{HF_TOKEN}'); "
        f"api = HfApi(); "
        f"api.upload_file(path_or_fileobj='{checkpoint}', path_in_repo='pytorch_model.bin', repo_id='{model_name}', token='{HF_TOKEN}'); "
        f"print('PUBLISHED')\"",
    ]
    publish_script = " && ".join(publish_cmds)

    rc, out, err = await ssh_command(ips[0], publish_script, timeout=1800)

    success = "PUBLISHED" in out
    result = {
        "model_name": model_name,
        "checkpoint": checkpoint,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "output": out[:1000],
        "url": f"https://huggingface.co/{model_name}",
    }

    if success:
        models = _load_published()
        models.append(result)
        _save_published(models)

    return result
