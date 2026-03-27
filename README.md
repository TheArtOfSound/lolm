# LOLM — Latent Order Language Model

A hybrid Transformer-SSM architecture that separates surface token prediction from latent state tracking. At 1.57B parameters on H200, LOLM achieves **33.2 PPL** versus **39.1** for a matched decoder-only baseline at step ~24K — a **15% improvement** (training ongoing). Cross-hardware validation on Google TPU v4 confirms LOLM converges **up to 43% faster** than a parameter-matched baseline during early training.

> **Key finding:** The latent SSM path comprises only ~29% of the fused representation, yet removing it causes perplexity to explode from 34.5 to **485 million** — a 14,000,000x increase. We call this *dependency inversion*: the minority path becomes increasingly critical at scale.

## Architecture

LOLM processes each token through five parallel streams that converge via learned fusion:

```
o_t = g * LN(W_h * h_t) + (1 - g) * LN(W_z * z_t) + W_m * m_t + W_r * r_t
```

| Stream | Role | Implementation |
|--------|------|----------------|
| **Surface Decoder** | Local token relationships | Pre-norm Transformer + RoPE |
| **Latent SSM Core** | Slow latent dynamics | Selective SSM (Mamba-style), parallel scan |
| **Regime Layer** | Discrete phase detection | Gumbel-Softmax + causal conv1d neighbor interaction |
| **Persistent Memory** | Cross-sequence state | 3-bank (episodic/semantic/self), gated read/write |
| **Manifestation Gate** | Surface vs latent arbitration | Per-dimension sigmoid, 2-layer MLP |

## Results

### LOLM-1.57B vs Matched Decoder-Only Baseline (FineWeb-Edu)

| Metric | LOLM-1.57B | Baseline | Delta |
|--------|-----------|----------|-------|
| Parameters | 1.57B | ~1.57B | matched |
| PPL (step ~24K) | **33.2** | 39.1 | **-15.1%** |
| Gate equilibrium | 0.72 | — | learned |
| Regimes alive | **64/64** | — | full utilization |

Both models trained on FineWeb-Edu with identical data, batch size, and comparable parameter count.

### TPU v4-8 Convergence (319M LOLM vs 317M Matched Baseline)

| Step | LOLM PPL | Baseline PPL | Delta | Winner |
|------|----------|-------------|-------|--------|
| 3,000 | **1,583** | 2,801 | +43.5% | LOLM |
| 5,000 | **828** | 1,141 | +27.4% | LOLM |
| 10,000 | **570** | 644 | +11.5% | LOLM |
| 15,000 | **439** | 443 | +0.9% | LOLM |
| 20,000 | 387 | **374** | -3.5% | Baseline |
| 50,000 | 260 | **249** | -4.4% | Baseline |

Both models trained on FineWeb-Edu with identical hyperparameters. PPL = exp(avg loss) over 200-step windows. LOLM dominates early training; baseline catches up around step 15-20K.

### LOLM-304M vs Pythia-410M (WikiText-103)

| Metric | LOLM-304M | Pythia-410M | Delta |
|--------|-----------|-------------|-------|
| Parameters | 304M | 410M | -26% |
| Eval PPL | **68.37** | 142.93 | **-52.2%** |
| Late-position BPC | 1.02 | 1.23 | -17.0% |
| Distinct-2 (generation) | 0.687 | 0.607 | +13.2% |

### 1.57B Gate Ablation (step 20,000)

| Configuration | PPL | Delta |
|---------------|-----|-------|
| Normal (g ≈ 0.71) | **34.47** | — |
| Surface Only (g = 1.0) | 485,165,195 | +1.4 billion % |
| Latent Only (g = 0.0) | 56,130 | +162,744% |

The surface decoder *cannot function* without the latent SSM — deep bidirectional integration confirmed.

### 304M Component Ablation (inference-time)

| Configuration | PPL | Delta |
|---------------|-----|-------|
| Full LOLM | **59.23** | — |
| No Regime | 123.73 | +109% |
| No SSM (gate=1) | 499.96 | +744% |
| No Gate (gate=0.5) | 595.43 | +905% |
| Decoder Only | 2,198.58 | +3,612% |

## Quick Start

### Install

```bash
git clone https://github.com/TheArtOfSound/LOLM.git
cd LOLM

# CPU / Apple Silicon (MPS)
pip install -r requirements.txt

# NVIDIA GPU (CUDA) — adds mamba-ssm kernels
pip install -r requirements-gpu.txt
```

### Train

```bash
# Base model (~20M params, runs on Mac)
python train.py --config configs/base.yaml

# 304M params (H200 or equivalent, ~4 hrs to convergence)
python train.py --config configs/scale/300m_v3.yaml

# 1.57B params (H200 140GB, bfloat16)
python train.py --config configs/scale/1b_v3.4.yaml
```

### Evaluate

```bash
# Perplexity + generation + gate/regime analysis
python evaluate.py --checkpoint runs/your_run/ckpt_20000.pt --config configs/scale/300m_v3.yaml

# Inference-time component ablation (no retraining needed)
python ablation_eval.py --checkpoint runs/your_run/ckpt_20000.pt

# Gate ablation (surface-only vs latent-only vs normal)
python ablate_gate.py --checkpoint runs/your_run/ckpt_20000.pt
```

## Configuration

LOLM uses YAML configs with inheritance via `_base_`:

```yaml
_base_: configs/base.yaml

model:
  d_model: 1024
  n_heads: 16
  n_layers: 16
```

| Config | Params | Hardware | Notes |
|--------|--------|----------|-------|
| `configs/base.yaml` | 20.5M | Mac MPS / CPU | Quick experiments |
| `configs/scale/100m.yaml` | 149M | RTX 4090 | Mid-scale |
| `configs/scale/300m_v3.yaml` | 304M | H200 | Published results |
| `configs/scale/1b_v3.4.yaml` | 1.57B | H200 140GB | Best model |
| `configs/scale/1b_baseline.yaml` | ~1.57B | H200 140GB | Decoder-only control |
| `configs/scale/300m_lolm_full_tpu.yaml` | 319M | TPU v4-8 | Full LOLM on TPU |
| `configs/scale/300m_baseline_matched_params.yaml` | 317M | TPU v4-8 | Matched baseline |
| `configs/ablations/01-06*.yaml` | 20.5M | Mac MPS | Ablation variants |

## Project Structure

```
lolm/                        # Core library
  config.py                  #   YAML config loader + dataclasses
  rope.py                    #   Rotary position embeddings
  decoder.py                 #   Pre-norm Transformer decoder
  ssm.py                     #   Selective SSM (CUDA / efficient / parallel / sequential)
  memory.py                  #   3-bank persistent memory with chunked writes
  regime.py                  #   Gumbel-Softmax regime layer + neighbor interaction
  gate.py                    #   Manifestation gate (per-dimension)
  losses.py                  #   7 training objectives
  model.py                   #   Full LOLM model wiring
  data.py                    #   Local data loading + tokenization
  data_streaming.py          #   HuggingFace streaming for large datasets

train.py                     # Training loop (AMP, grad accum, DDP, torch.compile)
evaluate.py                  # Perplexity, generation, gate/regime analysis
ablation_eval.py             # Inference-time component ablation
ablate_gate.py               # Gate ablation (surface-only / latent-only)
compare_baseline.py          # Matched baseline comparison
configs/                     # YAML configurations (base + scale + ablations)
```

## Training Objectives

LOLM trains with 7 complementary losses:

| Loss | λ | Description |
|------|---|-------------|
| **L_tok** | 1.0 | Next-token cross-entropy (chunked for memory efficiency) |
| **L_CPC** | 0.5 | Contrastive predictive coding — SSM state predicts future decoder state |
| **L_chg** | 0.1 | Changepoint alignment — regime transitions track representation shifts |
| **L_reg** | 0.3 | Regime diversity — load-balancing + entropy + sticky transitions |
| **L_comp** | 0.1 | Competitive gate — gate learns which branch predicts better |
| **L_mem** | 0.05 | Memory focus — encourage selective (low-entropy) memory reads |
| **L_manifest** | 0.01 | Gate regularizer — gentle bias toward latent-preferring output |

## Key Technical Contributions

- **Gradient isolation** for discrete codes: detaching regime embeddings from the token loss solves regime collapse (all 64 codes remain active at 1.57B)
- **Per-dimension gating** between surface and latent paths, with branch normalization
- **SimCLR-style CPC projection** heads solving the dimensionality-temperature mismatch at high d_model
- **Chunked memory writes** enabling gradient flow through persistent memory
- **Causal conv1d neighbor interaction** for spatially coherent regime segments

## Citation

```bibtex
@article{leonard2026lolm,
  title     = {LOLM: Language Modeling Beyond the Surface with Hybrid
               Transformer-SSM Latent Order Fields},
  author    = {Leonard, Bryan and Leonard, Brandyn},
  year      = {2026},
  note      = {Qira LLC. Provisional patent application No. 64002166.
               Code: \url{https://github.com/TheArtOfSound/LOLM}}
}
```

## License

LOLM is released under the [LOLM Community License Agreement, Version 1.0](LICENSE).

- **Free** for academic research, education, personal/non-commercial use, and small entities
- **Commercial license required** for qualifying commercial entities (revenue >$5M, funding >$10M, or >100 employees)

See [LICENSE](LICENSE) for full terms.

---

Copyright 2026 Bryan Leonard & Brandyn Leonard — Qira LLC
