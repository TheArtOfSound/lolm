"""LOLM-NFET graft modules for frozen Hugging Face backbones.

Practical target:
    frozen pretrained LM hidden states -> LOLM latent-order adapter ->
    residual correction + NFET control signals.

This version uses the repository's real ``LatentSSMCore`` by default. A tiny GRU
fallback remains available only for debugging environments where the selective
SSM path is too slow or unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from lolm.ssm import LatentSSMCore

LatentBackend = Literal["selective_ssm", "gru_debug"]
AblationMode = Literal["full", "no_latent", "no_regime", "no_gate", "no_residual", "latent_only"]


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
    ablation_mode: str = "full"


class LatentGRUDebugPath(nn.Module):
    """Cheap recurrent latent path reserved for debugging only."""

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
    """Discrete phase detector with soft regime probabilities.

    Uses the same survival principles as LOLM proper:
      - clamped logits
      - local neighbor interaction
      - Gumbel-Softmax
      - detached regime embedding before fusion
    """

    def __init__(self, d_model: int, n_regimes: int = 32, temperature: float = 0.7) -> None:
        super().__init__()
        self.n_regimes = n_regimes
        self.temperature = temperature
        self.proj = nn.Linear(d_model, n_regimes)
        self.emb = nn.Embedding(n_regimes, d_model)
        self.smooth = nn.Conv1d(n_regimes, n_regimes, kernel_size=5, padding=4)

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        logits = self.proj(hidden).clamp(-5.0, 5.0)
        smooth_in = logits.transpose(1, 2)
        smooth_logits = self.smooth(smooth_in)[:, :, : logits.size(1)].transpose(1, 2)
        probs = F.gumbel_softmax(logits + 0.1 * smooth_logits, tau=self.temperature, hard=False, dim=-1)
        regime = probs @ self.emb.weight
        return probs, regime.detach()

    def disabled(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        probs = torch.full(
            (*hidden.shape[:2], self.n_regimes),
            fill_value=1.0 / float(self.n_regimes),
            device=hidden.device,
            dtype=hidden.dtype,
        )
        regime = torch.zeros_like(hidden)
        return probs, regime


class ManifestationAdapter(nn.Module):
    """Per-dimension manifestation gate and residual correction."""

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

    def forward(
        self,
        surface: torch.Tensor,
        latent: torch.Tensor,
        regime: torch.Tensor,
        mode: AblationMode = "full",
    ) -> tuple[torch.Tensor, torch.Tensor]:
        s = self.surface_norm(surface)
        z = self.latent_norm(latent)
        r = self.regime_norm(regime)
        gate = self.gate(torch.cat([s, z, r], dim=-1))
        if mode == "no_gate":
            gate = torch.full_like(gate, 0.5)
        elif mode == "latent_only":
            gate = torch.zeros_like(gate)
        elif mode == "no_latent":
            gate = torch.ones_like(gate)
        fused = gate * s + (1.0 - gate) * z + 0.1 * r
        return self.residual(fused), gate


class NFETController(nn.Module):
    """Controller head over trajectory observables.

    Control classes:
        0 continue
        1 retrieve memory
        2 verify/criticize
        3 branch/explore
        4 stop/finalize
    """

    def __init__(self, d_model: int, n_controls: int = 5) -> None:
        super().__init__()
        hidden = max(64, d_model // 2)
        self.head = nn.Sequential(
            nn.Linear(d_model + 4, hidden),
            nn.GELU(),
            nn.Linear(hidden, n_controls),
        )

    def forward(
        self,
        corrected_hidden: torch.Tensor,
        base_logits: Optional[torch.Tensor],
        gate: torch.Tensor,
        regime_probs: torch.Tensor,
        drift_override: Optional[torch.Tensor] = None,
    ) -> NFETState:
        pooled = corrected_hidden.mean(dim=1)
        if drift_override is not None:
            # Streaming generation calls the graft with T=1, where in-sequence
            # drift is undefined; callers supply lag-1 drift across calls.
            drift = drift_override.to(device=corrected_hidden.device, dtype=corrected_hidden.dtype)
        elif corrected_hidden.size(1) > 1:
            drift = (corrected_hidden[:, 1:] - corrected_hidden[:, :-1]).pow(2).mean(dim=(1, 2))
        else:
            drift = torch.zeros(corrected_hidden.size(0), device=corrected_hidden.device, dtype=corrected_hidden.dtype)
        gate_mean = gate.mean(dim=(1, 2))
        regime_probs_safe = regime_probs.clamp_min(1e-8)
        regime_entropy = -(regime_probs_safe * regime_probs_safe.log()).sum(dim=-1).mean(dim=1)
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

    def __init__(
        self,
        d_model: int,
        d_latent: Optional[int] = None,
        n_regimes: int = 32,
        residual_scale: float = 0.1,
        latent_backend: LatentBackend = "selective_ssm",
        ssm_layers: int = 1,
        ssm_d_state: int = 16,
        ssm_expand: int = 1,
        use_cuda_kernels: bool = False,
    ) -> None:
        super().__init__()
        d_latent = d_latent or max(128, d_model // 4)
        self.d_model = d_model
        self.residual_scale = residual_scale
        self.latent_backend = latent_backend
        if latent_backend == "selective_ssm":
            self.latent = LatentSSMCore(
                d_model=d_model,
                n_layers=ssm_layers,
                d_state=ssm_d_state,
                expand=ssm_expand,
                use_cuda_kernels=use_cuda_kernels,
            )
        elif latent_backend == "gru_debug":
            self.latent = LatentGRUDebugPath(d_model=d_model, d_latent=d_latent)
        else:
            raise ValueError(f"Unknown latent backend: {latent_backend}")
        self.regime = RegimeDetector(d_model=d_model, n_regimes=n_regimes)
        self.adapter = ManifestationAdapter(d_model=d_model)
        self.nfet = NFETController(d_model=d_model)

    def forward(
        self,
        hidden: torch.Tensor,
        base_logits: Optional[torch.Tensor] = None,
        ablation_mode: AblationMode = "full",
        drift_override: Optional[torch.Tensor] = None,
    ) -> GraftOutput:
        if ablation_mode == "no_residual":
            latent = torch.zeros_like(hidden)
            regime_probs, _ = self.regime.disabled(hidden)
            gate = torch.ones_like(hidden)
            residual = torch.zeros_like(hidden)
            corrected = hidden
        else:
            latent = self.latent(hidden)
            if ablation_mode == "no_latent":
                latent = torch.zeros_like(hidden)
            if ablation_mode == "no_regime":
                regime_probs, regime = self.regime.disabled(hidden)
            else:
                regime_probs, regime = self.regime(hidden)
            residual, gate = self.adapter(hidden, latent, regime, mode=ablation_mode)
            corrected = hidden + self.residual_scale * residual
        nfet_state = self.nfet(corrected, base_logits=base_logits, gate=gate, regime_probs=regime_probs, drift_override=drift_override)
        return GraftOutput(
            corrected_hidden=corrected,
            residual=residual,
            gate=gate,
            regime_probs=regime_probs,
            nfet_state=nfet_state,
            ablation_mode=ablation_mode,
        )


def graft_regularization_loss(output: GraftOutput) -> Dict[str, torch.Tensor]:
    """Auxiliary losses that keep the graft measurable and non-collapsed."""
    regime_probs = output.regime_probs.clamp_min(1e-8)
    token_entropy = -(regime_probs * regime_probs.log()).sum(dim=-1).mean()
    usage = regime_probs.mean(dim=(0, 1))
    usage_entropy = -(usage * usage.clamp_min(1e-8).log()).sum()
    n_regimes = regime_probs.size(-1)
    max_entropy = torch.log(torch.tensor(float(n_regimes), device=regime_probs.device))
    return {
        "regime_token_entropy_reward": -token_entropy,
        "regime_usage_entropy_reward": -(usage_entropy / max_entropy),
        "gate_balance": (output.gate.mean() - 0.7).pow(2),
        "residual_l2": output.residual.pow(2).mean(),
    }
