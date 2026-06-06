"""LOLM-NFET graft modules for frozen Hugging Face backbones.

This file implements the first practical target:
    frozen pretrained LM hidden states -> trainable latent-order adapter ->
    residual correction + NFET control signals.

It is intentionally compact and dependency-light. The first milestone is to
prove positive signal before replacing this SSM stub with the full LOLM SSM
implementation already present in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class NFETState:
    """Observable dynamical-control state for the current sequence."""

    logit_entropy: torch.Tensor
    hidden_drift: torch.Tensor
    gate_mean: torch.Tensor
    regime_entropy: torch.Tensor
    control_logits: torch.Tensor


@dataclass
class GraftOutput:
    corrected_hidden: torch.Tensor
    residual: torch.Tensor
    gate: torch.Tensor
    regime_probs: torch.Tensor
    nfet_state: NFETState


class LatentSSMStub(nn.Module):
    """Cheap recurrent latent path used for first graft tests.

    This is not the final LOLM selective SSM. It gives us a trainable slow path
    with deterministic shape behavior so we can validate the HF graft pipeline.
    Replace with the repository's full selective SSM after the smoke tests pass.
    """

    def __init__(self, d_model: int, d_latent: int) -> None:
        super().__init__()
        self.in_proj = nn.Linear(d_model, d_latent)
        self.gru = nn.GRU(d_latent, d_latent, batch_first=True)
        self.out_proj = nn.Linear(d_latent, d_model)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, hidden: torch.Tensor) -> torch.Tensor:
        x = torch.tanh(self.in_proj(hidden))
        z, _ = self.gru(x)
        return self.norm(self.out_proj(z))


class RegimeDetector(nn.Module):
    """Discrete phase detector with soft regime probabilities."""

    def __init__(self, d_model: int, n_regimes: int = 32, temperature: float = 0.7) -> None:
        super().__init__()
        self.n_regimes = n_regimes
        self.temperature = temperature
        self.proj = nn.Linear(d_model, n_regimes)
        self.emb = nn.Embedding(n_regimes, d_model)
        self.smooth = nn.Conv1d(n_regimes, n_regimes, kernel_size=5, padding=4, groups=1)

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        logits = self.proj(hidden).clamp(-5.0, 5.0)
        # Causal-ish smoothing: conv pads both sides, then trim future positions.
        smooth_in = logits.transpose(1, 2)
        smooth_logits = self.smooth(smooth_in)[:, :, : logits.size(1)].transpose(1, 2)
        probs = F.gumbel_softmax(logits + 0.1 * smooth_logits, tau=self.temperature, hard=False, dim=-1)
        # Gradient isolation: the embedding injected into fusion is detached from token loss.
        regime = probs @ self.emb.weight
        return probs, regime.detach()


class ManifestationAdapter(nn.Module):
    """Per-dimension gate and residual correction."""

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.surface_norm = nn.LayerNorm(d_model)
        self.latent_norm = nn.LayerNorm(d_model)
        self.regime_norm = nn.LayerNorm(d_model)
        self.gate = nn.Sequential(
            nn.Linear(d_model * 3, d_model * 2),
            nn.GELU(),
            nn.Linear(d_model * 2, d_model),
            nn.Sigmoid(),
        )
        self.residual = nn.Sequential(
            nn.Linear(d_model, d_model * 2),
            nn.GELU(),
            nn.Linear(d_model * 2, d_model),
        )

    def forward(self, surface: torch.Tensor, latent: torch.Tensor, regime: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        s = self.surface_norm(surface)
        z = self.latent_norm(latent)
        r = self.regime_norm(regime)
        gate = self.gate(torch.cat([s, z, r], dim=-1))
        fused = gate * s + (1.0 - gate) * z + 0.1 * r
        return self.residual(fused), gate


class NFETController(nn.Module):
    """Small controller head over trajectory observables.

    Control classes are deliberately abstract for now:
        0 continue, 1 retrieve, 2 verify, 3 branch, 4 stop
    The controller can be supervised later with task traces.
    """

    def __init__(self, d_model: int, n_controls: int = 5) -> None:
        super().__init__()
        self.head = nn.Sequential(
            nn.Linear(d_model + 4, d_model // 2),
            nn.GELU(),
            nn.Linear(d_model // 2, n_controls),
        )

    def forward(
        self,
        corrected_hidden: torch.Tensor,
        base_logits: Optional[torch.Tensor],
        gate: torch.Tensor,
        regime_probs: torch.Tensor,
    ) -> NFETState:
        pooled = corrected_hidden.mean(dim=1)
        drift = (corrected_hidden[:, 1:] - corrected_hidden[:, :-1]).pow(2).mean(dim=(1, 2))
        gate_mean = gate.mean(dim=(1, 2))
        regime_entropy = -(regime_probs.clamp_min(1e-8) * regime_probs.clamp_min(1e-8).log()).sum(dim=-1).mean(dim=1)
        if base_logits is None:
            logit_entropy = torch.zeros_like(gate_mean)
        else:
            log_probs = F.log_softmax(base_logits[:, -1, :], dim=-1)
            probs = log_probs.exp()
            logit_entropy = -(probs * log_probs).sum(dim=-1)
        features = torch.cat(
            [
                pooled,
                logit_entropy[:, None],
                drift[:, None],
                gate_mean[:, None],
                regime_entropy[:, None],
            ],
            dim=-1,
        )
        return NFETState(
            logit_entropy=logit_entropy,
            hidden_drift=drift,
            gate_mean=gate_mean,
            regime_entropy=regime_entropy,
            control_logits=self.head(features),
        )


class LOLMNFETGraft(nn.Module):
    """Trainable LOLM-NFET graft for a frozen pretrained LM."""

    def __init__(self, d_model: int, d_latent: Optional[int] = None, n_regimes: int = 32, residual_scale: float = 0.1) -> None:
        super().__init__()
        d_latent = d_latent or max(128, d_model // 4)
        self.d_model = d_model
        self.residual_scale = residual_scale
        self.latent = LatentSSMStub(d_model=d_model, d_latent=d_latent)
        self.regime = RegimeDetector(d_model=d_model, n_regimes=n_regimes)
        self.adapter = ManifestationAdapter(d_model=d_model)
        self.nfet = NFETController(d_model=d_model)

    def forward(self, hidden: torch.Tensor, base_logits: Optional[torch.Tensor] = None) -> GraftOutput:
        latent = self.latent(hidden)
        regime_probs, regime = self.regime(hidden)
        residual, gate = self.adapter(hidden, latent, regime)
        corrected = hidden + self.residual_scale * residual
        nfet_state = self.nfet(corrected, base_logits=base_logits, gate=gate, regime_probs=regime_probs)
        return GraftOutput(
            corrected_hidden=corrected,
            residual=residual,
            gate=gate,
            regime_probs=regime_probs,
            nfet_state=nfet_state,
        )


def graft_regularization_loss(output: GraftOutput) -> Dict[str, torch.Tensor]:
    """Auxiliary losses that keep the graft measurable and non-collapsed."""
    regime_probs = output.regime_probs.clamp_min(1e-8)
    token_entropy = -(regime_probs * regime_probs.log()).sum(dim=-1).mean()
    usage = regime_probs.mean(dim=(0, 1))
    usage_entropy = -(usage * usage.clamp_min(1e-8).log()).sum()
    n_regimes = regime_probs.size(-1)
    max_entropy = torch.log(torch.tensor(float(n_regimes), device=regime_probs.device))
    losses = {
        "regime_token_entropy_reward": -token_entropy,
        "regime_usage_entropy_reward": -(usage_entropy / max_entropy),
        "gate_balance": (output.gate.mean() - 0.7).pow(2),
        "residual_l2": output.residual.pow(2).mean(),
    }
    return losses
