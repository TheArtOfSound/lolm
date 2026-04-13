"""Benchmark evaluation runner, cost tracker, and training comparisons for LOLM."""

import os
import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from auth import require_auth
from training import ssh_command, get_tpu_ips
from tpu import DEFAULT_ZONE

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"], dependencies=[Depends(require_auth)])


# Published LOLM results from the paper
PUBLISHED_RESULTS = {
    "lolm_304m": {
        "name": "LOLM-304M",
        "params": "303.6M",
        "dataset": "FineWeb-Edu",
        "eval_dataset": "WikiText-103",
        "ppl": 68.37,
        "bpc": 6.10,
        "comparison": "Pythia-410M: 142.93 PPL at matched compute (52.2% better)",
        "context_advantage": "+45.4%",
        "late_position_bpc": "-17.0%",
        "distinct_2": 0.687,
        "bigram_repetition": "31.3%",
        "gate_mean": 0.83,
        "regimes_alive": "32/32",
        "training_tokens": "~2B",
    },
    "lolm_1_57b": {
        "name": "LOLM-1.57B",
        "params": "1.57B",
        "dataset": "FineWeb-Edu",
        "ppl": 33.2,
        "comparison": "Matched baseline: 39.1 PPL (15% better)",
        "gate_mean": 0.72,
        "regimes_alive": "64/64",
        "cpc_future": 5.69,
        "training_tokens": "~1.5B",
    },
    "ablations_304m": {
        "name": "Component Ablation (304M)",
        "results": [
            {"config": "Full LOLM", "ppl": 59.23, "delta": "—"},
            {"config": "No Memory", "ppl": 59.23, "delta": "+0.0%"},
            {"config": "No Regime", "ppl": 123.73, "delta": "+108.9%"},
            {"config": "No SSM (gate→1)", "ppl": 499.96, "delta": "+744.1%"},
            {"config": "No Gate (gate→0.5)", "ppl": 595.43, "delta": "+905.2%"},
            {"config": "Decoder Only", "ppl": 2198.58, "delta": "+3611.8%"},
        ],
    },
    "gate_ablation_1_57b": {
        "name": "1.57B Gate Ablation",
        "results": [
            {"config": "Normal (g≈0.71)", "loss": 3.54, "ppl": 34.47, "delta": "—"},
            {"config": "Surface Only (g=1.0)", "loss": 76.89, "ppl": 485165195, "delta": "+14,075,632×"},
            {"config": "Latent Only (g=0.0)", "loss": 10.94, "ppl": 56130, "delta": "+162,744%"},
        ],
    },
    "scaling": {
        "name": "Scaling Behavior",
        "results": [
            {"scale": "20.5M", "dataset": "TinyStories", "loss_20k": 2.62, "ppl_20k": 13.7, "gate": 0.27, "regimes": "1/16"},
            {"scale": "149M", "dataset": "FineWeb-Edu", "loss_20k": 4.15, "ppl_20k": 63.2, "gate": 0.55, "regimes": "1/24"},
            {"scale": "304M", "dataset": "FineWeb-Edu", "loss_20k": 3.57, "ppl_20k": 35.5, "gate": 0.83, "regimes": "32/32"},
            {"scale": "1.57B", "dataset": "FineWeb-Edu", "loss_20k": 3.50, "ppl_20k": 33.2, "gate": 0.72, "regimes": "64/64"},
        ],
    },
    "tpu_comparison": {
        "name": "TPU Training Comparison (319M vs 317M baseline)",
        "results": [
            {"step": 3000, "lolm_ppl": 1583, "baseline_ppl": 2801, "delta": "+43.5%"},
            {"step": 5000, "lolm_ppl": 828, "baseline_ppl": 1141, "delta": "+27.4%"},
            {"step": 7500, "lolm_ppl": 664, "baseline_ppl": 807, "delta": "+17.7%"},
            {"step": 10000, "lolm_ppl": 570, "baseline_ppl": 644, "delta": "+11.5%"},
            {"step": 15000, "lolm_ppl": 439, "baseline_ppl": 443, "delta": "+0.9%"},
            {"step": 20000, "lolm_ppl": 387, "baseline_ppl": 374, "delta": "-3.5%"},
            {"step": 25000, "lolm_ppl": 299, "baseline_ppl": 286, "delta": "-4.8%"},
            {"step": 50000, "lolm_ppl": 260, "baseline_ppl": 249, "delta": "-4.4%"},
        ],
    },
}

# TPU cost rates (approximate)
TPU_COSTS = {
    "v4-8": {"on_demand": 12.88, "spot": 4.00},      # $/hr
    "v4-32": {"on_demand": 103.04, "spot": 32.00},
    "v6e-64": {"on_demand": 120.00, "spot": 40.00},
    "v5e-64": {"on_demand": 100.00, "spot": 33.00},
}


@router.get("/results")
async def get_published_results():
    """Return all published LOLM results from the paper."""
    return PUBLISHED_RESULTS


@router.get("/cost")
async def estimate_cost(
    tpu_type: str = "v4-32",
    hours: float = 24,
    spot: bool = True,
):
    """Estimate training cost."""
    rates = TPU_COSTS.get(tpu_type, TPU_COSTS["v4-32"])
    rate = rates["spot"] if spot else rates["on_demand"]
    cost = rate * hours
    return {
        "tpu_type": tpu_type,
        "rate_per_hour": rate,
        "hours": hours,
        "spot": spot,
        "total_cost": round(cost, 2),
        "cost_per_day": round(rate * 24, 2),
    }


@router.post("/run-eval")
async def run_evaluation(
    tpu_name: str = "lolm-7b",
    checkpoint: Optional[str] = None,
    benchmark: str = "wikitext-103",
    zone: str = DEFAULT_ZONE,
):
    """Launch a benchmark evaluation on a TPU VM.

    Runs downstream_eval_tpu.py on the TPU with the specified checkpoint.
    """
    ips = await get_tpu_ips(tpu_name, zone)
    if not ips:
        return {"error": f"No IPs for {tpu_name}"}

    eval_cmd = f"cd ~/Latent && python3 downstream_eval_tpu.py --benchmark {benchmark}"
    if checkpoint:
        eval_cmd += f" --checkpoint {checkpoint}"

    rc, out, err = await ssh_command(ips[0], eval_cmd, timeout=600)
    return {
        "benchmark": benchmark,
        "checkpoint": checkpoint,
        "output": out[-2000:] if out else "",
        "error": err[-500:] if err else "",
        "success": rc == 0,
    }


# Reference training curves from other LLMs at similar scale
# Used for comparison on the dashboard
TRAINING_REFERENCES = {
    "lolm_7b_base_tpu": {
        "name": "LOLM-7B Decoder Baseline (TPU v4-32)",
        "params": "~7B",
        "hardware": "v4-32",
        "note": "Pure Transformer decoder baseline trained alongside LOLM on same data",
        "steps": [1000, 2000, 3000, 5000, 7500, 10000, 15000],
        "loss":  [8.5,   7.2,  6.8,  6.2,  5.8,   5.5,   5.1],
    },
    "lolm_300m_tpu": {
        "name": "LOLM-319M (TPU v4, Paper Table 5)",
        "params": "319M",
        "hardware": "v4-8",
        "steps": [3000, 5000, 7500, 10000, 15000, 20000, 25000, 50000],
        "loss":  [7.36,  6.71, 6.49,  6.35,  6.08,  5.96,  5.70, 5.56],
    },
    "lolm_300m_baseline_tpu": {
        "name": "Baseline-317M (TPU v4, Paper Table 5)",
        "params": "317M",
        "hardware": "v4-8",
        "steps": [3000, 5000, 7500, 10000, 15000, 20000, 25000, 50000],
        "loss":  [7.94,  7.04, 6.69,  6.47,  6.09,  5.93,  5.66, 5.52],
    },
    "pythia_410m": {
        "name": "Pythia-410M (EleutherAI, The Pile)",
        "params": "410M",
        "hardware": "8× A100",
        "note": "From Biderman et al. 2023. Trained on The Pile (300B tokens).",
        "final_ppl_wikitext": 142.93,
    },
    "pythia_1b": {
        "name": "Pythia-1B (EleutherAI, The Pile)",
        "params": "1B",
        "hardware": "8× A100",
        "note": "From Biderman et al. 2023.",
        "final_ppl_wikitext": 54.0,
    },
    "llama_7b": {
        "name": "LLaMA-7B (Meta, 2023)",
        "params": "6.7B",
        "hardware": "2048× A100",
        "note": "Trained on 1T tokens. PPL on WikiText-103.",
        "final_ppl_wikitext": 12.6,
        "training_tokens": "1T",
    },
    "gpt2_small": {
        "name": "GPT-2 Small (OpenAI)",
        "params": "124M",
        "hardware": "256× V100",
        "final_ppl_wikitext": 37.5,
        "training_tokens": "~40B",
    },
    "gpt2_medium": {
        "name": "GPT-2 Medium (OpenAI)",
        "params": "355M",
        "hardware": "256× V100",
        "final_ppl_wikitext": 26.4,
        "training_tokens": "~40B",
    },
    "gpt2_large": {
        "name": "GPT-2 Large (OpenAI)",
        "params": "774M",
        "hardware": "256× V100",
        "final_ppl_wikitext": 22.1,
        "training_tokens": "~40B",
    },
    "mamba_1_4b": {
        "name": "Mamba-1.4B (Gu & Dao, 2023)",
        "params": "1.4B",
        "hardware": "8× A100",
        "note": "Pure SSM, no attention. Trained on The Pile (300B tokens).",
        "final_ppl_wikitext": 16.1,
        "training_tokens": "300B",
    },
}


@router.get("/comparisons")
async def get_training_comparisons():
    """Return reference training curves and final metrics for comparison."""
    return TRAINING_REFERENCES


@router.get("/compare-live")
async def compare_live_to_references(current_loss: float = 40.0, current_step: int = 200, current_params_m: int = 951):
    """Compare current live training to reference models at similar step counts."""
    comparisons = []

    # Find references with step data
    for key, ref in TRAINING_REFERENCES.items():
        if "steps" in ref and "loss" in ref:
            # Interpolate to find loss at current step
            steps = ref["steps"]
            losses = ref["loss"]
            if current_step <= steps[0]:
                interp_loss = losses[0]
            elif current_step >= steps[-1]:
                interp_loss = losses[-1]
            else:
                for i in range(len(steps) - 1):
                    if steps[i] <= current_step <= steps[i + 1]:
                        frac = (current_step - steps[i]) / (steps[i + 1] - steps[i])
                        interp_loss = losses[i] + frac * (losses[i + 1] - losses[i])
                        break
                else:
                    interp_loss = losses[-1]

            delta = ((current_loss - interp_loss) / interp_loss) * 100
            comparisons.append({
                "name": ref["name"],
                "params": ref["params"],
                "ref_loss_at_step": round(interp_loss, 3),
                "current_loss": round(current_loss, 3),
                "delta_pct": round(delta, 1),
                "better": current_loss < interp_loss,
            })

    return {
        "current": {"loss": current_loss, "step": current_step, "params": f"{current_params_m}M"},
        "comparisons": comparisons,
    }
