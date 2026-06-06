"""Projection helper for HF + LOLM-NFET graft experiments."""

from __future__ import annotations

import torch
import torch.nn.functional as F


def project_with_backbone_lm_head(backbone_model, hidden: torch.Tensor) -> torch.Tensor:
    """Project hidden states through a Hugging Face causal-LM output head.

    HF checkpoints may keep the LM head on a specific device and dtype, while the
    LOLM-NFET graft may run in float32 for local stability. Aligning here avoids
    hard-to-read matmul dtype/device errors during local chat and eval.
    """
    head = backbone_model.get_output_embeddings()
    if head is None:
        raise ValueError("Backbone has no output embedding / LM head")
    weight = getattr(head, "weight", None)
    if weight is not None:
        hidden = hidden.to(device=weight.device, dtype=weight.dtype)
    return head(hidden)


def shifted_language_model_loss(logits: torch.Tensor, labels: torch.Tensor, ignore_index: int = -100) -> torch.Tensor:
    """Standard next-token loss for already-computed logits."""
    shift_logits = logits[:, :-1, :].contiguous()
    shift_labels = labels[:, 1:].contiguous()
    return F.cross_entropy(
        shift_logits.view(-1, shift_logits.size(-1)),
        shift_labels.view(-1),
        ignore_index=ignore_index,
    )
