"""LOLM config management — read/write/validate YAML configs with paper descriptions."""

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends
from auth import require_auth

# Add LOLM root to path so we can import config module
LOLM_ROOT = Path(__file__).resolve().parent.parent  # dashboard/ dir, which contains configs/ and lolm/
sys.path.insert(0, str(LOLM_ROOT))

router = APIRouter(prefix="/api/configs", tags=["configs"], dependencies=[Depends(require_auth)])

CONFIGS_DIR = LOLM_ROOT / "configs" / "scale"


# Paper descriptions for every LOLM parameter
SCHEMA = {
    "model": {
        "_description": "LOLM architecture — hybrid Transformer-SSM with 5 parallel subsystems",
        "d_model": {"type": "int", "default": 4096, "description": "Hidden dimension. Shared across decoder, SSM, memory, gate. Paper §3.1: 'At the 304M scale: d=1024'"},
        "n_heads": {"type": "int", "default": 32, "description": "Number of attention heads in the Surface Decoder. Each head has dim = d_model / n_heads."},
        "n_layers": {"type": "int", "default": 32, "description": "Number of DecoderBlock layers in the Surface Decoder (pre-norm Transformer + RoPE). Paper §3.1."},
        "d_ff": {"type": "int", "default": 8192, "description": "Feed-forward hidden dimension. Standard ratio is 2-4× d_model. Paper uses GELU (not SwiGLU)."},
        "vocab_size": {"type": "int", "default": 50257, "description": "GPT-2 tokenizer vocabulary size (intentionally prime). FSDP requires flatten_parameters=True."},
        "max_seq_len": {"type": "int", "default": 256, "description": "Maximum sequence length for RoPE position encoding and attention mask."},
        "dropout": {"type": "float", "default": 0.05, "description": "Dropout rate for attention and FFN layers."},
        "ssm": {
            "_description": "Latent SSM Core — Mamba-style selective state-space model (Paper §3.2)",
            "enabled": {"type": "bool", "default": True, "description": "Enable the latent SSM path. The SSM processes decoder hidden states h through selective state-space recurrence, tracking slow latent dynamics — semantic drift, unresolved plans, topic evolution."},
            "n_layers": {"type": "int", "default": 1, "description": "Number of SSM layers. Paper: K=4 at 304M, K=6 at 1.57B. Reduced to 1 for TPU v4-32 HBM budget."},
            "d_state": {"type": "int", "default": 64, "description": "SSM state dimension N. The recurrent state s_t ∈ R^(d_inner × d_state). Paper: N=32 at 304M, N=64 at 1.57B."},
            "expand": {"type": "int", "default": 2, "description": "SSM expansion factor. d_inner = d_model × expand. Controls SSM capacity."},
            "use_cuda_kernels": {"type": "bool", "default": False, "description": "Use mamba-ssm CUDA kernels (GPU only). On TPU, uses sequential scan fallback."},
            "detach_gradients": {"type": "bool", "default": True, "description": "Detach SSM output z before fusion (Eq.1). SSM trained only by CPC loss, not token loss. Prevents scan BPTT NaN on XLA."},
        },
        "regime": {
            "_description": "Regime Layer — discrete phase detection via Gumbel-Softmax (Paper §3.4)",
            "enabled": {"type": "bool", "default": True, "description": "Enable discrete regime codes. Assigns each token a soft distribution over R codes via Gumbel-Softmax."},
            "n_codes": {"type": "int", "default": 64, "description": "Number of regime codes R. Paper: R=32 at 304M, R=64 at 1.57B."},
            "d_regime": {"type": "int", "default": 256, "description": "Regime embedding dimension. The codebook E_r ∈ R^(R × d_regime)."},
            "temp_start": {"type": "float", "default": 1.0, "description": "Initial Gumbel-Softmax temperature τ. High temperature = more exploration."},
            "temp_end": {"type": "float", "default": 0.5, "description": "Final temperature. Paper: 'We do not anneal to near-zero: maintaining stochasticity at τ=0.5 allows continued exploration.'"},
            "temp_anneal_steps": {"type": "int", "default": 200000, "description": "Steps over which temperature linearly anneals from temp_start to temp_end."},
            "neighbor_interaction": {"type": "bool", "default": True, "description": "Enable causal Conv1d neighbor interaction (kernel=7). Creates spatially coherent regime segments. Inspired by MPST Ising-model dynamics."},
            "neighbor_kernel_size": {"type": "int", "default": 7, "description": "Kernel size for causal Conv1d neighbor interaction."},
            "gradient_isolation": {"type": "bool", "default": True, "description": "CRITICAL: Detach regime embedding r_t before fusion (Eq.1). Regime trained only by its own losses. Prevents code collapse. Paper §5.4: 'Without isolation, all 32 codes collapse to a single active code within 500-2000 steps.'"},
        },
        "memory": {
            "_description": "Persistent Memory — 3 banks (episodic, semantic, self-model) with gated read/write (Paper §3.3)",
            "enabled": {"type": "bool", "default": True, "description": "Enable persistent memory. Required when regime is enabled (d_regime_in = h+z+m = 3×d_model)."},
            "n_slots": {"type": "int", "default": 128, "description": "Number of memory slots per bank. Each slot is a learnable vector. Paper: N=128 at 304M."},
            "n_banks": {"type": "int", "default": 3, "description": "Number of memory banks: episodic (events), semantic (facts), self-model (agent state). All three concatenated for readout."},
            "slot_dim": {"type": "int", "default": 4096, "description": "Dimension of each memory slot vector. Must equal d_model for attention compatibility."},
            "n_chunks": {"type": "int", "default": 4, "description": "Number of intra-sequence chunks for memory write gradient flow. Paper §3.3: 'Without chunking, write parameters receive zero gradient.'"},
        },
        "gate": {
            "_description": "Manifestation Gate — per-dimension mixing of surface vs latent representations (Paper §3.5)",
            "enabled": {"type": "bool", "default": True, "description": "Enable per-dimension manifestation gate g_t ∈ [0,1]^d. Controls how much output is surface-decoder vs latent-SSM driven."},
            "init_bias": {"type": "float", "default": -0.5, "description": "Bias initialization for gate output layer. -0.5 → sigmoid(-0.5) ≈ 0.38, biasing toward latent-preferring at init. Paper §3.5."},
            "normalize_branches": {"type": "bool", "default": True, "description": "Apply LayerNorm to both h and z branches before gating. Prevents magnitude mismatch (Paper Eq.1)."},
        },
    },
    "training": {
        "_description": "Training hyperparameters — AdamW (FSDP decoder) + SGD (replicated subsystems)",
        "batch_size": {"type": "int", "default": 1, "description": "Per-chip batch size. Global batch = batch_size × grad_accum × world_size."},
        "grad_accumulation_steps": {"type": "int", "default": 1, "description": "Gradient accumulation micro-steps before optimizer update."},
        "seq_len": {"type": "int", "default": 256, "description": "Sequence length per sample. Also determines SSM scan unrolling depth on XLA."},
        "max_steps": {"type": "int", "default": 50000, "description": "Total training steps."},
        "lr": {"type": "float", "default": 1.5e-4, "description": "Peak learning rate. Paper: 3e-4 at 304M, 1.5e-4 at 1.57B."},
        "weight_decay": {"type": "float", "default": 0.1, "description": "AdamW weight decay. Standard 0.1 for LLM pretraining."},
        "beta1": {"type": "float", "default": 0.9, "description": "AdamW β₁ (momentum coefficient)."},
        "beta2": {"type": "float", "default": 0.95, "description": "AdamW β₂ (variance coefficient). 0.95 is standard for LLM training."},
        "warmup_steps": {"type": "int", "default": 2000, "description": "Linear warmup steps before cosine decay begins."},
        "grad_clip": {"type": "float", "default": 0.5, "description": "Gradient clipping norm. Paper: 1.0 at 304M, 0.5 at larger scales."},
        "dtype": {"type": "str", "default": "bfloat16", "description": "Training precision. bfloat16 on TPU v4 (native MXU support, 275 TFLOPS)."},
        "log_interval": {"type": "int", "default": 10, "description": "Log metrics every N steps."},
        "save_interval": {"type": "int", "default": 500, "description": "Checkpoint save interval. Frequent for spot TPU preemption recovery."},
    },
    "loss": {
        "_description": "7-component multi-objective loss (Paper §4.1, Table 8)",
        "lambda_future": {"type": "float", "default": 0.5, "description": "CPC contrastive loss weight (L_CPC). The latent state z_t should encode information about future decoder states h_{t+k}. Uses InfoNCE with SimCLR projection heads."},
        "lambda_changepoint": {"type": "float", "default": 0.1, "description": "Changepoint alignment weight (L_chg). Pearson correlation between regime transitions and representation changepoints."},
        "lambda_regime": {"type": "float", "default": 0.3, "description": "Regime diversity weight (L_reg). Combines load-balancing, per-token entropy, and sticky-transition penalties."},
        "lambda_competitive": {"type": "float", "default": 0.1, "description": "Competitive gate weight (L_comp). Trains gate to track which branch (surface vs latent) better predicts the future."},
        "lambda_mem": {"type": "float", "default": 0.05, "description": "Memory focus weight (L_mem). Minimizes normalized attention entropy to encourage selective memory reads."},
        "lambda_manifest": {"type": "float", "default": 0.01, "description": "Gate regularizer weight (L_manifest). E[g_t], gentle bias toward latent-preferring output."},
        "lambda_balance": {"type": "float", "default": 0.1, "description": "MoE-style load-balance within regime diversity loss."},
        "lambda_sticky": {"type": "float", "default": 0.01, "description": "Sticky-transition penalty within regime diversity. Encourages regime persistence across adjacent tokens."},
        "cpc_proj_dim": {"type": "int", "default": 128, "description": "CPC projection dimension. Paper §4.1: 'Projecting to 128 dims yields cosine sim std ≈0.088, which at τ=0.07 gives logit std ≈1.26 — the sweet spot for InfoNCE.'"},
        "cpc_temperature": {"type": "float", "default": 0.07, "description": "CPC InfoNCE temperature for cosine similarity scaling."},
        "future_window": {"type": "int", "default": 8, "description": "CPC future prediction window k. z_t predicts h_{t+k}."},
        "cpc_max_positions": {"type": "int", "default": 256, "description": "Maximum positions subsampled for CPC loss. Static slice to avoid XLA dynamic shape issues."},
    },
    "data": {
        "_description": "Dataset configuration",
        "streaming": {"type": "bool", "default": True, "description": "Use HuggingFace streaming API (pre-downloads parquet to local before xmp.spawn on TPU)."},
        "dataset": {"type": "str", "default": "HuggingFaceFW/fineweb-edu", "description": "HuggingFace dataset name or local path to parquet files."},
        "tokenizer": {"type": "str", "default": "gpt2", "description": "Tokenizer name (tiktoken). GPT-2 BPE with vocab_size=50257."},
    },
}


@router.get("")
@router.get("/")
async def list_configs():
    """List all YAML config files."""
    configs = []
    if CONFIGS_DIR.exists():
        for f in sorted(CONFIGS_DIR.glob("*.yaml")):
            configs.append({"name": f.name, "path": str(f)})
    return {"configs": configs}


@router.get("/schema")
async def get_schema():
    """Return full LOLM config schema with paper descriptions."""
    return SCHEMA


@router.get("/{name}")
async def get_config(name: str):
    """Read a config file, resolving _base_ inheritance."""
    config_path = CONFIGS_DIR / name
    if not config_path.exists():
        return {"error": f"Config {name} not found"}
    try:
        from lolm.config import load_config
        cfg = load_config(str(config_path))
        # Convert dataclass to dict
        import dataclasses
        def _to_dict(obj: Any) -> Any:
            if dataclasses.is_dataclass(obj):
                return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
            return obj
        return {"name": name, "config": _to_dict(cfg)}
    except Exception as e:
        # Fallback: raw YAML
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        return {"name": name, "config": raw, "warning": f"Could not resolve _base_: {e}"}


@router.put("/{name}")
async def update_config(name: str, config: dict):
    """Write updated config YAML."""
    config_path = CONFIGS_DIR / name
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    return {"success": True, "name": name}
