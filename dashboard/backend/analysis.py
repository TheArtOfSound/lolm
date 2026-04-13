"""AI-powered training analysis — uses OpenRouter (GPT-4o/Claude) for insights every 5 min."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from auth import require_auth

router = APIRouter(prefix="/api/analysis", tags=["analysis"], dependencies=[Depends(require_auth)])

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-4o-mini"  # Fast + cheap for analysis

# Cache analyses on disk
DATA_DIR = Path("/opt/lolm-dashboard/data")
DATA_DIR.mkdir(exist_ok=True)
ANALYSIS_FILE = DATA_DIR / "analyses.json"

# Rate limit: one analysis per 5 min
_last_analysis_time = 0


def _load_analyses() -> list:
    try:
        return json.loads(ANALYSIS_FILE.read_text())
    except Exception:
        return []


def _save_analysis(analysis: dict):
    analyses = _load_analyses()
    analyses.append(analysis)
    # Keep last 100
    if len(analyses) > 100:
        analyses = analyses[-100:]
    ANALYSIS_FILE.write_text(json.dumps(analyses, indent=2, default=str))


async def _call_llm(prompt: str) -> str:
    """Call OpenRouter API for analysis."""
    if not OPENROUTER_KEY:
        return "No API key configured. Set OPENROUTER_API_KEY."

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": """You are an expert analyst for LOLM (Latent Order Language Model), a novel hybrid Transformer-SSM architecture. Key facts about LOLM:

1. LOLM has 5 parallel subsystems: Surface Decoder (Transformer), Latent SSM (Mamba-style), Persistent Memory (3 banks), Regime Layer (Gumbel-Softmax discrete codes), and Manifestation Gate (per-dimension g∈[0,1]).

2. The gate value g: LOW gate (0.2-0.4) in early training is NORMAL and GOOD — it means the model relies on the latent SSM path for inductive bias before the Transformer matures. The paper shows gate drops to 0.17 early, then rises to 0.7-0.8 by convergence. A low gate at step 2500 is expected behavior.

3. CPC future loss: random chance is ln(256)=5.55. ANY value below 5.55 means the SSM is learning. The paper shows CPC breaks below chance around step 1500 and reaches 0.15 by step 30K. So values like 5.4 at step 2500 are on track.

4. Regime codes: all codes staying alive (32/32 or 64/64) confirms gradient isolation is working — this is the VQ-VAE-style fix from the paper.

5. Loss trajectory: larger models start with higher loss and take longer to converge. A 1B model at step 2500 with loss ~8-10 is normal — it's only seen ~0.04B tokens. Compare to tokens seen, not step count.

Be accurate about what's good vs concerning. Don't over-alarm. Max 250 words."""},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"API error: {resp.status_code}"


@router.post("/run")
async def run_analysis(
    step: int = 0,
    loss: float = 0,
    loss_tok: float = 0,
    ppl: float = 0,
    gate: float = 0,
    regimes: int = 0,
    cpc_future: float = 0,
    params_m: int = 951,
    steps_per_sec: float = 0.4,
):
    """Run AI analysis on current training state."""
    global _last_analysis_time

    now = time.time()
    if now - _last_analysis_time < 60:  # Min 1 min between analyses
        recent = _load_analyses()
        if recent:
            return {"analysis": recent[-1], "cached": True}
        return {"error": "Rate limited, no cached analysis"}

    _last_analysis_time = now

    prompt = f"""Analyze this LOLM training run:

Model: LOLM-1B ({params_m}M params) — hybrid Transformer-SSM with 5 subsystems
Hardware: Google Cloud TPU v4-32 (16 chips, 32GB HBM each)
Dataset: FineWeb-Edu (streaming)
Step: {step} / 50,000
Token Loss: {loss_tok:.4f}
Total Loss: {loss:.4f} (includes 7 loss components)
Perplexity: {ppl:.1f}
Gate Mean: {gate:.3f} (0=fully latent SSM, 1=fully surface decoder)
Active Regime Codes: {regimes}/32
CPC Future Loss: {cpc_future:.4f} (random chance = 5.55)
Training Speed: {steps_per_sec:.1f} steps/sec

Reference points:
- LOLM-304M at step 20K: loss=3.57, PPL=35.5, gate=0.83
- LOLM-1.57B at step 20K: loss=3.50, PPL=33.2, gate=0.72
- GPT-2 Small (124M) final WikiText-103 PPL: 37.5
- Pythia-410M final WikiText-103 PPL: 142.9
- Pythia-1B final WikiText-103 PPL: 54.0

Questions:
1. Is the loss trajectory healthy for this model size at this step count?
2. What does the gate value (currently {gate:.3f}) tell us about surface vs latent reliance?
3. Is the CPC future loss ({cpc_future:.4f}) showing the SSM is learning?
4. Predicted loss at step 10K and 50K based on current trajectory?
5. Any concerns or recommendations?"""

    response = await _call_llm(prompt)

    analysis = {
        "step": step,
        "loss": loss,
        "ppl": ppl,
        "gate": gate,
        "analysis": response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
    }
    _save_analysis(analysis)

    return {"analysis": analysis, "cached": False}


@router.get("/latest")
async def get_latest_analysis():
    """Get the most recent analysis."""
    analyses = _load_analyses()
    if not analyses:
        return {"analysis": None}
    return {"analysis": analyses[-1]}


@router.get("/history")
async def get_analysis_history(limit: int = 20):
    """Get analysis history."""
    analyses = _load_analyses()
    return {"analyses": analyses[-limit:]}
