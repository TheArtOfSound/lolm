# LOLM — Latent Order Language Model

A hybrid Transformer-SSM language model that explicitly separates surface token prediction from latent state tracking, achieving significantly lower perplexity than comparable decoder-only models.

## Overview

LOLM processes each token through five parallel streams:

1. **Surface Decoder** — Pre-norm Transformer with RoPE for local token relationships
2. **Latent SSM Core** — Selective state-space model (Mamba-style) tracking slow-changing latent dynamics
3. **Regime Layer** — Discrete phase detection via Gumbel-Softmax with neighbor interaction
4. **Persistent Memory** — Three-bank (episodic/semantic/self) attention-based memory with gated writes
5. **Manifestation Gate** — Per-dimension learned gating between surface and latent representations

These streams converge through a gated fusion equation:

```
o_t = g * LN(W_h * h_t) + (1 - g) * LN(W_z * z_t) + W_m * m_t + W_r * r_t
```

Where `g` is a per-dimension gate in [0, 1] that learns context-dependent arbitration between the surface decoder (h) and latent SSM (z).

## Results

### LOLM-304M vs Pythia-410M (WikiText-103)

| Metric | LOLM-304M | Pythia-410M | Delta |
|--------|-----------|-------------|-------|
| Parameters | 304M | 410M | -26% |
| Eval PPL | 68.37 | 142.93 | **-52.2%** |
| Late-position BPC | 1.02 | 1.23 | -17.0% |
| Distinct-2 (generation) | 0.687 | 0.607 | +13.2% |

### Component Ablation (304M)

| Configuration | PPL | Delta |
|---------------|-----|-------|
| Full LOLM | 59.23 | — |
| No SSM (gate=1) | 499.96 | +744% |
| No Gate (gate=0.5) | 595.43 | +905% |
| No Regime | 123.73 | +109% |
| Decoder Only | 2,198.58 | +3,612% |

The latent SSM contributes only ~17% of the fused representation at convergence, yet removing it increases perplexity by 744%.

## Quick Start

### Install

```bash
# CPU / MPS (Mac)
pip install -r requirements.txt

# GPU (CUDA)
pip install -r requirements-gpu.txt
```

### Train (base, ~20M params)

```bash
python train.py --config configs/base.yaml
```

### Train at scale

```bash
# 304M params (requires H200 or equivalent)
python train.py --config configs/scale/300m_v3.yaml

# 1.57B params
python train.py --config configs/scale/1b_v3.4.yaml
```

### Evaluate

```bash
python evaluate.py --checkpoint runs/your_run/best.pt --config configs/base.yaml
```

### Run ablations

```bash
python ablation.py
```

## Configuration

LOLM uses YAML configuration with inheritance. Set a `_base_` key to inherit from another config:

```yaml
_base_: configs/base.yaml

d_model: 1024
n_heads: 16
n_layers: 16
```

Available configs:
- `configs/base.yaml` — 20.5M params (Mac MPS)
- `configs/scale/100m.yaml` — 149M params (RTX 4090)
- `configs/scale/300m_v3.yaml` — 304M params (H200)
- `configs/scale/1b_v3.4.yaml` — 1.57B params (H200)
- `configs/ablations/01-06*.yaml` — Ablation variants

## Project Structure

```
lolm/
  __init__.py          # Package init
  config.py            # Configuration dataclasses + YAML loader
  rope.py              # Rotary position embeddings
  decoder.py           # Pre-norm Transformer decoder
  ssm.py               # Selective SSM (4 scan backends)
  memory.py            # 3-bank persistent memory
  regime.py            # Gumbel-Softmax regime layer
  gate.py              # Manifestation gate
  losses.py            # 7 training losses
  model.py             # Full model wiring
  data.py              # Data loading + tokenization
  data_streaming.py    # HuggingFace streaming

train.py               # Training loop (AMP, grad accumulation, DDP)
evaluate.py            # Evaluation + generation
ablation.py            # Ablation runner
configs/               # YAML configurations
```

## Training Losses

LOLM uses 7 training objectives:

| Loss | Description |
|------|-------------|
| L_tok | Next-token cross-entropy (chunked for memory efficiency) |
| L_CPC | Contrastive predictive coding — latent state predicts future decoder state |
| L_chg | Changepoint alignment — regime transitions track representation boundaries |
| L_reg | Regime diversity — load-balancing + entropy + sticky transitions |
| L_comp | Competitive gate — gate tracks which branch predicts better |
| L_mem | Memory focus — encourage selective (low-entropy) memory reads |
| L_manifest | Gate regularizer — penalize unnecessary externalization |

## License

LOLM is released under the [LOLM Community License Agreement, Version 1.0](LICENSE).

- **Free** for academic research, education, personal/non-commercial use, and small entities
- **Commercial license required** for qualifying commercial entities

Contact: bryanleonard237@gmail.com

---

Copyright 2026 Bryan Leonard & Brandyn Leonard — Qira LLC
