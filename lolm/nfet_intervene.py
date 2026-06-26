# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Interventional K — the do-calculus causal-consequence measure NFET's K-channel needs.

Correlational K (any local graft signal) failed F4. This computes the real thing: at
token i, intervene on the residual stream (a noising `do`, as in causal tracing / ROME),
let the remaining attention layers propagate it, and measure how much the DOWNSTREAM token
distribution diverges from the unperturbed run:

    K_int(i) = mean_{i<j<=i+h}  KL( P(x_j | do(perturb_i)) || P(x_j) ).

This is §2/§4's effective-information of the event, measured by actual intervention rather
than guessed from a local feature. The test it enables: does any CHEAP local signal recover
K_int? If yes, the implemented K-channel is justified (use that signal). If no, NFET's causal
channel genuinely requires the expensive intervention — and we say so.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import torch
import torch.nn.functional as F


def _decoder_layers(model) -> List:
    """Find the ModuleList of decoder blocks across common HF architectures."""
    for path in ("model.layers", "model.decoder.layers", "transformer.h", "gpt_neox.layers"):
        obj = model
        ok = True
        for part in path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                ok = False
                break
        if ok and len(list(obj)) > 0:
            return list(obj)
    raise RuntimeError("could not locate decoder layers for intervention")


def interventional_k(backbone, text: str, *, layer_frac: float = 0.5, eps: float = 3.0,
                     horizon: int = 4, draws: int = 3, seed: int = 0
                     ) -> Dict[int, float]:
    """K_int per token position via a noising do-intervention on a mid layer."""
    model = backbone.model
    device = next(model.parameters()).device
    layers = _decoder_layers(model)
    k = max(0, min(len(layers) - 1, int(layer_frac * len(layers))))
    batch = backbone.tokenizer(text, return_tensors="pt")
    batch = {kk: v.to(device) for kk, v in batch.items()}
    T = batch["input_ids"].size(1)
    if T < horizon + 3:
        return {}

    with torch.no_grad():
        base_logits = model(**batch).logits[0]                  # (T, V)
        base_lp = F.log_softmax(base_logits.float(), dim=-1)

    out: Dict[int, float] = {}
    gen = torch.Generator(device="cpu").manual_seed(seed)
    for i in range(1, T - horizon):
        kls_over_draws = []
        for d in range(draws):
            def hook(module, inp, output, _pos=i, _g=gen):
                h = output[0] if isinstance(output, tuple) else output
                h = h.clone()
                vec = h[:, _pos, :]
                scale = vec.norm(dim=-1, keepdim=True) / (h.size(-1) ** 0.5)
                noise = torch.randn(vec.shape, generator=_g).to(h.device, h.dtype) * eps * scale
                h[:, _pos, :] = vec + noise
                return (h,) + tuple(output[1:]) if isinstance(output, tuple) else h
            handle = layers[k].register_forward_hook(hook)
            with torch.no_grad():
                pert_logits = model(**batch).logits[0]
            handle.remove()
            pert_lp = F.log_softmax(pert_logits.float(), dim=-1)
            pert_p = pert_lp.exp()
            kls = []
            for j in range(i + 1, min(i + 1 + horizon, T)):
                kl = float((pert_p[j] * (pert_lp[j] - base_lp[j])).sum())
                kls.append(kl)
            kls_over_draws.append(sum(kls) / max(len(kls), 1))
        out[i] = sum(kls_over_draws) / len(kls_over_draws)
    return out
