"""Reusable training step for frozen-HF + LOLM-NFET graft."""

from __future__ import annotations

from typing import Dict

import torch

from lolm.hf_lm_head import project_with_backbone_lm_head, shifted_language_model_loss
from lolm.nfet_graft import graft_regularization_loss


def scalar(x: torch.Tensor) -> float:
    return float(x.detach().float().cpu().item())


def graft_train_step(backbone, graft, batch: Dict[str, torch.Tensor], optimizer, grad_clip: float = 1.0) -> Dict[str, float]:
    labels = batch["input_ids"].clone()
    if "attention_mask" in batch:
        labels = labels.masked_fill(batch["attention_mask"] == 0, -100)

    with torch.no_grad():
        base = backbone(**batch)
    # Frozen backbones often run in bf16 while the graft trains in fp32;
    # MPS matmul asserts on mixed dtypes, so cast to the graft's dtype.
    param = next(graft.parameters())
    hidden = base.hidden_states.detach().to(dtype=param.dtype)
    base_logits = base.logits.detach().to(dtype=param.dtype)
    out = graft(hidden, base_logits=base_logits)
    logits = project_with_backbone_lm_head(backbone.model, out.corrected_hidden)
    token_loss = shifted_language_model_loss(logits, labels)
    aux = graft_regularization_loss(out)
    loss = (
        token_loss
        + 0.02 * aux["regime_token_entropy_reward"]
        + 0.05 * aux["regime_usage_entropy_reward"]
        + 0.01 * aux["gate_balance"]
        + 0.001 * aux["residual_l2"]
    )

    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(graft.parameters(), grad_clip)
    optimizer.step()

    return {
        "loss": scalar(loss),
        "token_loss": scalar(token_loss),
        "gate_mean": scalar(out.gate.mean()),
        "regime_entropy": scalar(out.nfet_state.regime_entropy.mean()),
        "hidden_drift": scalar(out.nfet_state.hidden_drift.mean()),
        "logit_entropy": scalar(out.nfet_state.logit_entropy.mean()),
    }
