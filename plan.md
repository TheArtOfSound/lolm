# LOLM (Latent Order Language Model) — Implementation Plan

## What We're Building

A ~19M parameter language model where token generation is conditioned on:
- A **persistent latent order field** (selective SSM, Mamba-style)
- A **discrete regime/phase state** (Gumbel-Softmax)
- A **long-term memory substrate** (3 gated banks)
- A **manifestation gate** controlling when internal structure becomes text

All pure PyTorch, MPS-compatible, trainable on your 24GB Mac Air.

---

## Parameter Budget

| Component | Params |
|-----------|--------|
| Token Embedding (50257 x 256) | 12.87M |
| Surface Decoder (6 layers) | 4.72M |
| Latent SSM Core (2 layers) | 0.59M |
| Regime Layer (16 codes) | 0.20M |
| Persistent Memory (3 banks x 32 slots) | 0.42M |
| Manifestation Gate | 0.21M |
| **Total** | **~19M** |

LM Head is weight-tied with embedding (0 extra params).

---

## Directory Structure

```
latent/
├── requirements.txt
├── configs/
│   ├── base.yaml
│   └── ablations/
│       ├── 01_plain_decoder.yaml
│       ├── 02_decoder_memory.yaml
│       ├── 03_decoder_ssm.yaml
│       ├── 04_decoder_ssm_memory.yaml
│       ├── 05_decoder_ssm_memory_regime.yaml
│       └── 06_full.yaml
├── lolm/
│   ├── __init__.py
│   ├── config.py          # Dataclass configs + YAML loader
│   ├── rope.py            # Rotary positional encoding
│   ├── decoder.py         # 6-layer Transformer decoder
│   ├── ssm.py             # Selective SSM latent core (pure PyTorch scan)
│   ├── regime.py          # Gumbel-Softmax regime layer
│   ├── memory.py          # 3-bank persistent memory
│   ├── gate.py            # Manifestation gate
│   ├── model.py           # Full LOLM wiring all modules
│   ├── losses.py          # 5-objective loss
│   └── data.py            # Tokenization + dataloader
├── train.py               # Training loop
├── evaluate.py            # Perplexity, generation, regime/gate analysis
├── prepare_data.py        # One-time data tokenization
├── ablation.py            # Run all 6 ablation configs
└── count_params.py        # Print param counts per module
```

14 Python files, 7 YAML configs.

---

## Architecture — Forward Pass

```
token_ids (B, 512)
     │
     ▼
  SurfaceDecoder ──────► h (B, 512, 256)
                           │     │     │
                           │     │     └──► Memory ──► m (B, 512, 256)
                           │     │                │
                           │     └──► SSM ──► z (B, 512, 256)
                           │              │        │
                           │              ▼        ▼
                           │          RegimeLayer
                           │              │
                           │              ▼
                           │          r_embed (B, 512, 64)
                           │              │
                           ▼              ▼
                      ManifestationGate(z, r, m, h)
                           │
                           ▼
                      h_gated = g*h + (1-g)*z
                           │
                           + m (residual)
                           │
                           ▼
                      LM Head (tied weights)
                           │
                           ▼
                      logits (B, 512, 50257)
```

---

## Module Specs

### Surface Decoder
- 6 layers, pre-norm, d_model=256, 8 heads (head_dim=32)
- RoPE positional encoding (no learned params)
- Uses `F.scaled_dot_product_attention(is_causal=True)` — MPS compatible
- FFN: 256→1024→256 with GELU
- Returns: final hidden state + per-layer states

### Latent SSM Core
- 2-layer selective state-space model
- d_inner=512 (expand=2), d_state=16
- Input-dependent dt, B, C projections (selective mechanism)
- Diagonal A matrix learned in log-space
- **Sequential Python scan** (no CUDA kernels) — slow but MPS-safe
- Each scan step: ~32K elements per batch item, ~0.5s total per batch

### Regime Layer
- Concatenates [z; h; m] → projects to 16 regime logits
- Gumbel-Softmax with temperature annealed 1.0→0.1 over 50K steps
- Regime embedding: 16 codes x 64 dims
- Returns: soft embedding, probabilities, argmax indices

### Persistent Memory
- 3 banks (episodic, semantic, self), 32 slots each, slot_dim=256
- Read: attention-based retrieval (query from hidden state)
- Write: gated, aggregated over sequence (not per-token for speed)
- Forget: per-slot sigmoid gating
- Combined via learned projection: 768→256

### Manifestation Gate
- Input: [z(256); r_embed(64); m(256); h(256)] = 832 dims
- 2-layer MLP → per-dimension sigmoid in [0,1]
- g≈1: surface decoder drives output (standard LM)
- g≈0: latent state drives output (novel behavior)

---

## Loss Functions (5 objectives)

| Loss | Weight | Purpose |
|------|--------|---------|
| L_tok | 1.0 | Standard next-token cross-entropy |
| L_future | 0.1 | z_t must predict summary of next 8 tokens (cosine sim, future detached) |
| L_regime | 0.05 | Entropy regularization + switch penalty (0.1) |
| L_mem | 0.05 | Memory attention entropy (encourage focused reads) |
| L_manifest | 0.01 | Mean gate activation (penalize unnecessary externalization) |

---

## Training Setup

- **Tokenizer**: tiktoken GPT-2 BPE (vocab 50257)
- **Data**: TinyStories (~470M tokens, ~940MB on disk as uint16)
- **Optimizer**: AdamW (lr=3e-4, weight_decay=0.1, betas=(0.9, 0.95))
- **Schedule**: Cosine with 1000-step linear warmup
- **Batch size**: 4, seq_len=512
- **Max steps**: 100K
- **Device**: MPS, FP32 (no autocast — MPS FP16 is unreliable)
- **Memory usage**: ~2GB total (model + optimizer + activations), well under 24GB

---

## Ablation Table (6 configs)

| # | Config | SSM | Memory | Regime | Gate |
|---|--------|-----|--------|--------|------|
| 1 | Plain decoder | ✗ | ✗ | ✗ | ✗ |
| 2 | + Memory | ✗ | ✓ | ✗ | ✗ |
| 3 | + SSM | ✓ | ✗ | ✗ | ✗ |
| 4 | + SSM + Memory | ✓ | ✓ | ✗ | ✗ |
| 5 | + SSM + Memory + Regime | ✓ | ✓ | ✓ | ✗ |
| 6 | Full model | ✓ | ✓ | ✓ | ✓ |

Each ablation config is a minimal YAML that only toggles enable flags.

---

## Build Order

Each step is independently testable:

1. `config.py` — load YAML, verify dataclass
2. `rope.py` — pure math, verify rotation
3. `decoder.py` — forward pass with random tokens, check shapes
4. `data.py` — tokenize small subset, iterate dataloader
5. `ssm.py` — random input, verify scan output shapes
6. `memory.py` — read/write cycle, check shapes
7. `regime.py` — Gumbel-Softmax at various temperatures
8. `gate.py` — sigmoid outputs in [0,1]
9. `losses.py` — dummy tensors, verify gradients flow
10. `model.py` — full forward pass, all output shapes correct
11. `train.py` — overfit on 1 batch as smoke test
12. `evaluate.py` — generate from untrained model
13. `ablation.py` — run config 01 for 100 steps
14. `count_params.py` — verify ~19M total

---

## MPS-Specific Considerations

- Sequential SSM scan (Python loop) instead of parallel CUDA scan
- `torch.mps.empty_cache()` every 100 steps
- FP32 only — no `torch.autocast("mps")`
- No `torch.compile` (unreliable on MPS)
- `num_workers=0` in DataLoader (MPS doesn't benefit from multiprocess)
- `pin_memory=False` (not applicable for MPS)

---

## Known Risks

1. **Latent collapse**: Decoder ignores SSM/memory. Mitigated by L_future forcing z to predict ahead.
2. **Regime jitter**: Phase layer flips randomly. Mitigated by switch penalty + entropy control.
3. **Memory bloat**: Writes everything, retrieves garbage. Mitigated by focused-read loss + forget gating.
4. **SSM scan speed**: ~0.5s per batch on MPS. Acceptable for prototype; can reduce T or expand factor if needed.
5. **Fancy theory, weak results**: Mitigated by ablation-first discipline — every component must earn its place.

---

## Success Criteria

The architecture works if the full model (config 06) beats plain decoder (config 01) on:
- Long-horizon coherence in generated text
- Latent z predicting future discourse structure
- Regime clusters aligning with meaningful text phases
- Memory improving delayed recall

While maintaining comparable perplexity.
