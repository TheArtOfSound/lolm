# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Licensed under the LOLM Community License Agreement, Version 1.0
# (the "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License in the
# LICENSE file at the root of this repository.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for specific terms and conditions.

"""LOLM v3 loss: multi-objective training losses.

Full v3 loss:
  L = L_tok + lambda_L * L_L + lambda_E * L_E + lambda_r * L_r + lambda_g * L_g + lambda_m * L_m

Where:
  L_tok  = next-token cross-entropy (standard LM objective)
  L_L    = CPC contrastive loss: z_t must encode future structure (InfoNCE)
  L_E    = changepoint alignment: regime transitions should track representation shifts
  L_r    = regime diversity: load-balancing + entropy + sticky transitions
  L_g    = competitive gate: gate should track which branch predicts better
  L_m    = memory focus: encourage non-uniform memory reads
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


def _safe_normalize(x: torch.Tensor, dim: int = -1, eps: float = 1e-6) -> torch.Tensor:
    """F.normalize that won't NaN on zero-norm vectors."""
    norm = x.norm(dim=dim, keepdim=True).clamp(min=eps)
    return x / norm


def _safe_loss(loss: torch.Tensor, max_val: float = 50.0) -> torch.Tensor:
    """Clamp loss and replace NaN/Inf with zero. Prevents backward OOM."""
    if torch.isnan(loss) or torch.isinf(loss):
        return torch.tensor(0.0, device=loss.device, requires_grad=True)
    return loss.clamp(-max_val, max_val)


class LOLMLoss(nn.Module):
    """Multi-objective loss for LOLM training."""

    def __init__(
        self,
        lambda_future: float = 0.1,
        lambda_regime: float = 0.05,
        lambda_mem: float = 0.05,
        lambda_manifest: float = 0.01,
        future_window: int = 8,
        lambda_balance: float = 0.1,
        use_load_balance: bool = False,
        lambda_sticky: float = 0.0,
        # v3 formal losses
        use_cpc: bool = False,
        cpc_temperature: float = 0.1,
        cpc_max_positions: int = 256,
        lambda_changepoint: float = 0.0,
        lambda_competitive: float = 0.0,
        # v3.2: CPC projection dimension (SimCLR/CLIP style)
        cpc_proj_dim: int = 0,
    ):
        super().__init__()
        self.lambda_future = lambda_future
        self.lambda_regime = lambda_regime
        self.lambda_mem = lambda_mem
        self.lambda_manifest = lambda_manifest
        self.future_window = future_window
        self.lambda_balance = lambda_balance
        self.use_load_balance = use_load_balance
        self.lambda_sticky = lambda_sticky

        # v3
        self.use_cpc = use_cpc
        self.cpc_temperature = cpc_temperature
        self.cpc_max_positions = cpc_max_positions
        self.lambda_changepoint = lambda_changepoint
        self.lambda_competitive = lambda_competitive
        self.cpc_proj_dim = cpc_proj_dim

        # Learned future summary projection (z -> predicted future embedding)
        self.future_proj = None  # Initialized lazily based on d_model
        # v3.2: CPC projection heads (SimCLR/CLIP style, lower dim)
        self.cpc_z_proj = None  # z → R^cpc_proj_dim
        self.cpc_h_proj = None  # h → R^cpc_proj_dim

    def _init_future_proj(self, d_model: int, device: torch.device):
        if self.future_proj is None:
            self.future_proj = nn.Linear(d_model, d_model, bias=False).to(device)

    def _init_cpc_proj(self, d_model: int, device: torch.device):
        """Initialize CPC projection heads (SimCLR/CLIP style).

        Projects both z and h into a lower-dimensional space where cosine
        similarity has enough variance for InfoNCE to learn.

        Math: In R^d, random unit vectors have cos_sim std ≈ 1/sqrt(d).
        At d=1024, std ≈ 0.031 → at temp=0.1, logit_std = 0.31 → uniform softmax.
        At d=128, std ≈ 0.088 → at temp=0.07, logit_std = 1.26 → learnable.

        v3.3: Use wider hidden layer (512) to avoid information crush when
        d_model >> d_proj (e.g. 2048→128 = 16x compression killed CPC at 1.57B).
        GELU replaces ReLU to prevent dead neurons in the projection.

        v3.4: Scale hidden layer with d_model to keep compression ratio ≤2x
        per layer. At 300M (d=1024): 1024→512→128 (2x, 4x). At 1.57B (d=2048):
        2048→1024→128 (2x, 8x). Previous fixed 512 bottleneck caused 4x first-
        layer compression at 1.57B, starving the projection of capacity.
        """
        d_proj = self.cpc_proj_dim
        d_hidden = max(d_proj * 4, d_model // 2)  # v3.4: scale with d_model
        if self.cpc_z_proj is None:
            self.cpc_z_proj = nn.Sequential(
                nn.Linear(d_model, d_hidden),
                nn.GELU(),
                nn.Linear(d_hidden, d_proj),
            ).to(device)
        if self.cpc_h_proj is None:
            self.cpc_h_proj = nn.Sequential(
                nn.Linear(d_model, d_hidden),
                nn.GELU(),
                nn.Linear(d_hidden, d_proj),
            ).to(device)

    def token_loss(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """Standard next-token cross-entropy, chunked to avoid OOM.

        F.cross_entropy upcasts to float32 internally, trying to materialize
        (B*T, vocab_size) = (65536, 50257) * 4 bytes = 12.3 GB on H200.
        Chunking to 4096 positions at a time caps this at ~780 MB.
        """
        V = logits.size(-1)
        logits_flat = logits.view(-1, V)
        targets_flat = targets.view(-1)
        n = logits_flat.size(0)

        chunk_size = 16384  # v3.4: larger chunks = fewer iterations (H200 has headroom)

        if n <= chunk_size:
            return F.cross_entropy(logits_flat, targets_flat, ignore_index=-1)

        loss_sum = 0.0  # becomes tensor after first chunk_loss addition
        num_valid = 0
        for i in range(0, n, chunk_size):
            j = min(i + chunk_size, n)
            chunk_loss = F.cross_entropy(
                logits_flat[i:j], targets_flat[i:j],
                ignore_index=-1, reduction="sum",
            )
            loss_sum = loss_sum + chunk_loss
            num_valid += (targets_flat[i:j] != -1).sum().item()

        return loss_sum / max(num_valid, 1)

    # ----------------------------------------------------------------
    # L_L: Latent order loss — CPC or cosine future prediction
    # ----------------------------------------------------------------

    def future_loss(self, z: torch.Tensor, h: torch.Tensor) -> torch.Tensor:
        """Dispatch to CPC or legacy cosine future loss."""
        if z is None:
            return torch.tensor(0.0, device=h.device)
        if self.use_cpc:
            return self.cpc_loss(z, h)
        return self._cosine_future_loss(z, h)

    def cpc_loss(self, z: torch.Tensor, h: torch.Tensor) -> torch.Tensor:
        """InfoNCE contrastive predictive coding.

        z_t should encode information about future h_{t+k}.
        Positive: the actual h_{t+k} at position t.
        Negatives: h_{t'+k} from other time positions in the same sequence.

        v3.2: When cpc_proj_dim > 0, both z and h are projected into a
        lower-dimensional space (SimCLR/CLIP style) where cosine similarity
        has enough variance for InfoNCE to bootstrap learning.
        """
        B, T, D = h.shape
        k = self.future_window
        if T <= k:
            return torch.tensor(0.0, device=h.device)

        valid = T - k

        if self.cpc_proj_dim > 0:
            # v3.2: Project both z and h to lower dim for learnable InfoNCE
            self._init_cpc_proj(D, z.device)
            z_proj = self.cpc_z_proj(z[:, :valid])              # (B, valid, d_proj)
            h_proj = self.cpc_h_proj(h[:, k:k + valid].detach())  # (B, valid, d_proj)
        else:
            # v3.0/v3.1: Single linear in full d_model (KNOWN TO NOT LEARN)
            self._init_future_proj(D, z.device)
            z_proj = self.future_proj(z[:, :valid])       # (B, valid, D)
            h_proj = h[:, k:k + valid].detach()           # (B, valid, D)

        # Normalize for cosine-based InfoNCE (safe against zero-norm)
        z_proj = _safe_normalize(z_proj, dim=-1)
        h_proj = _safe_normalize(h_proj, dim=-1)

        # Subsample positions — use a STATIC slice so XLA traces fixed shapes.
        # Dynamic stride (valid // max_positions) causes XLA to allocate the full
        # (B, T, T) similarity matrix at compile time, OOMing on v6e-4 (32GB HBM).
        n_pos = min(valid, self.cpc_max_positions)
        z_sub = z_proj[:, :n_pos]                       # (B, n_pos, d) — static shape
        h_sub = h_proj[:, :n_pos]                       # (B, n_pos, d) — static shape

        # Similarity matrix: each z_t against all h positions
        logits = torch.bmm(z_sub, h_sub.transpose(1, 2))  # (B, n_pos, n_pos)
        logits = logits / self.cpc_temperature

        # Clamp to prevent extreme softmax inputs that cause NaN in bfloat16.
        # At temp=0.07, max cosine sim of 1.0 → logit=14.3. Clamping at 30
        # is generous but prevents runaway values from destabilizing training.
        logits = logits.clamp(-30.0, 30.0)

        # Target: diagonal (z_t should match h_{t+k} at same t)
        labels = torch.arange(n_pos, device=h.device).unsqueeze(0).expand(B, -1)

        return _safe_loss(F.cross_entropy(logits.reshape(-1, n_pos), labels.reshape(-1)))

    def _cosine_future_loss(self, z: torch.Tensor, h: torch.Tensor) -> torch.Tensor:
        """Legacy cosine future loss (fallback when use_cpc=False)."""
        self._init_future_proj(z.size(-1), z.device)

        B, T, D = h.shape
        k = self.future_window
        if T <= k:
            return torch.tensor(0.0, device=h.device)

        h_padded = F.pad(h, (0, 0, 0, k), value=0.0)
        h_cumsum = h_padded.cumsum(dim=1)
        future_sum = h_cumsum[:, k:T + k] - h_cumsum[:, :T]
        future_mean = future_sum / k

        valid = T - k
        if valid <= 0:
            return torch.tensor(0.0, device=h.device)

        z_proj = self.future_proj(z[:, :valid])
        target = future_mean[:, :valid].detach()
        cos_sim = F.cosine_similarity(z_proj, target, dim=-1)
        return -cos_sim.mean()

    # ----------------------------------------------------------------
    # L_E: Changepoint alignment — regimes should track structure shifts
    # ----------------------------------------------------------------

    def changepoint_loss(
        self, h: torch.Tensor, regime_probs: torch.Tensor
    ) -> torch.Tensor:
        """Regime transitions should align with representation changepoints.

        Changepoints: positions where h_t shifts rapidly (low cosine sim
        between adjacent hidden states). Regime transitions should occur
        at these natural boundaries, not randomly.

        Uses Pearson correlation between changepoint signal and regime
        transition signal — maximizing this correlation anchors regimes
        to real structure in the data.
        """
        if regime_probs is None or h is None:
            return torch.tensor(0.0, device=h.device)

        B, T, D = h.shape
        if T <= 1:
            return torch.tensor(0.0, device=h.device)

        # Changepoint signal: 1 - cos_sim(h_t, h_{t-1})
        # High = big representation shift = natural boundary
        h_norm = _safe_normalize(h.detach(), dim=-1)
        h_cos = (h_norm[:, 1:] * h_norm[:, :-1]).sum(dim=-1)  # (B, T-1)
        changepoint = 1.0 - h_cos

        # Regime transition signal: 1 - cos_sim(probs_t, probs_{t-1})
        # High = regime switch
        prob_sim = F.cosine_similarity(
            regime_probs[:, 1:], regime_probs[:, :-1], dim=-1
        )
        regime_transition = 1.0 - prob_sim

        # Pearson correlation: regime transitions should correlate with changepoints
        cp = changepoint - changepoint.mean(dim=-1, keepdim=True)
        rt = regime_transition - regime_transition.mean(dim=-1, keepdim=True)

        denom = cp.norm(dim=-1) * rt.norm(dim=-1)
        # Guard: if either signal has zero variance, correlation is undefined
        valid = denom > 1e-6
        if not valid.any():
            return torch.tensor(0.0, device=h.device)
        correlation = (cp * rt).sum(dim=-1) / (denom + 1e-8)
        correlation = correlation[valid]

        return _safe_loss(-correlation.mean())  # minimize = maximize correlation

    # ----------------------------------------------------------------
    # L_g: Competitive gate — gate should track branch utility
    # ----------------------------------------------------------------

    def competitive_gate_loss(
        self,
        z: torch.Tensor,
        h: torch.Tensor,
        gate_values: torch.Tensor,
    ) -> torch.Tensor:
        """Gate should learn when latent state z is more useful than surface h.

        Computes future-prediction quality for each branch:
        - h_utility = cos_sim(h_t, h_{t+k})  (surface branch)
        - z_utility = cos_sim(z_t, h_{t+k})  (latent branch)

        When z predicts future better, gate should go low (latent-preferring).
        When h predicts future better, gate should go high (surface-preferring).

        This gives the gate a concrete, differentiable job instead of
        settling to a static blend.
        """
        if z is None or gate_values is None:
            return torch.tensor(0.0, device=h.device)

        B, T, D = h.shape
        k = self.future_window
        if T <= k:
            return torch.tensor(0.0, device=h.device)

        valid = T - k
        h_future = _safe_normalize(h[:, k:k + valid].detach(), dim=-1)

        # Surface branch utility: how well does h_t predict h_{t+k}?
        h_util = (
            _safe_normalize(h[:, :valid].detach(), dim=-1) * h_future
        ).sum(dim=-1)  # (B, valid)

        # Latent branch utility: how well does z_t predict h_{t+k}?
        z_util = (
            _safe_normalize(z[:, :valid].detach(), dim=-1) * h_future
        ).sum(dim=-1)  # (B, valid)

        # Target gate: high when h is better, low when z is better
        # Clamp advantage diff to prevent sigmoid saturation gradients
        advantage = torch.sigmoid((h_util - z_util).clamp(-5.0, 5.0) * 5.0)

        # Compare with actual gate (averaged over d_model channels)
        gate_mean = gate_values[:, :valid].mean(dim=-1)  # (B, valid)

        return _safe_loss(F.mse_loss(gate_mean, advantage))

    # ----------------------------------------------------------------
    # L_r: Regime diversity (load-balancing + entropy + sticky)
    # ----------------------------------------------------------------

    def regime_loss(
        self, probs: torch.Tensor, indices: torch.Tensor
    ) -> torch.Tensor:
        """Regime diversity loss."""
        if probs is None:
            return torch.tensor(
                0.0, device=indices.device if indices is not None else "cpu"
            )

        if self.use_load_balance:
            return self._load_balance_loss(probs)
        else:
            # Legacy (KNOWN TO CAUSE COLLAPSE)
            entropy = -(probs * probs.clamp(min=1e-7).log()).sum(dim=-1).mean()
            if indices.size(1) > 1:
                switches = (indices[:, 1:] != indices[:, :-1]).float().mean()
            else:
                switches = torch.tensor(0.0, device=probs.device)
            return entropy + 0.1 * switches

    def _load_balance_loss(self, probs: torch.Tensor) -> torch.Tensor:
        """MoE-style load-balancing + entropy maximization + sticky transitions."""
        n_codes = probs.size(-1)

        code_freq = probs.mean(dim=(0, 1))
        hard_assign = F.one_hot(probs.argmax(dim=-1), n_codes).float()
        route_freq = hard_assign.mean(dim=(0, 1))
        balance_loss = n_codes * (code_freq * route_freq).sum()

        per_token_entropy = -(probs * probs.clamp(min=1e-7).log()).sum(dim=-1).mean()
        neg_entropy = -per_token_entropy

        sticky_loss = torch.tensor(0.0, device=probs.device)
        if self.lambda_sticky > 0.0 and probs.size(1) > 1:
            sim = F.cosine_similarity(probs[:, 1:], probs[:, :-1], dim=-1)
            sticky_loss = -sim.mean()

        return (
            self.lambda_balance * balance_loss
            + neg_entropy
            + self.lambda_sticky * sticky_loss
        )

    # ----------------------------------------------------------------
    # L_m: Memory focus
    # ----------------------------------------------------------------

    def memory_loss(self, mem_read: torch.Tensor,
                    mem_attn: torch.Tensor = None) -> torch.Tensor:
        """Encourage focused memory reads via attention entropy.

        Low entropy = focused reads (good) — model attends to specific slots.
        High entropy = uniform reads (bad) — model spreads attention evenly.

        Normalized to [0, 1] so lambda_mem is scale-independent.

        Falls back to variance loss if attention weights not provided.
        """
        if mem_attn is not None:
            # Attention entropy: penalize uniform attention over memory slots
            # mem_attn: (B, T, n_slots) — softmax attention weights
            import math
            entropy = -(mem_attn * mem_attn.clamp(min=1e-7).log()).sum(dim=-1).mean()
            max_entropy = math.log(mem_attn.size(-1))
            return entropy / max_entropy  # normalized [0, 1], minimize = focus

        # Legacy fallback: variance loss
        if mem_read is None:
            return torch.tensor(0.0)
        var = mem_read.var(dim=-1).mean()
        return -var

    # ----------------------------------------------------------------
    # L_manifest (legacy, kept for backward compat)
    # ----------------------------------------------------------------

    def manifest_loss(self, gate_values: torch.Tensor) -> torch.Tensor:
        """Penalize unnecessary externalization (gate regularizer)."""
        if gate_values is None:
            return torch.tensor(0.0)
        return gate_values.mean()

    # ----------------------------------------------------------------
    # Forward: full v3 loss computation
    # ----------------------------------------------------------------

    def forward(
        self,
        logits: torch.Tensor,
        targets: torch.Tensor,
        z: torch.Tensor = None,
        h: torch.Tensor = None,
        regime_probs: torch.Tensor = None,
        regime_indices: torch.Tensor = None,
        mem_read: torch.Tensor = None,
        mem_attn: torch.Tensor = None,
        gate_values: torch.Tensor = None,
    ) -> tuple[torch.Tensor, dict]:
        """Compute total loss and component breakdown.

        v3 loss:
          L = L_tok + lambda_L * L_L + lambda_E * L_E
              + lambda_r * L_r + lambda_g * L_g + lambda_m * L_m
        """
        dev = logits.device
        l_tok = self.token_loss(logits, targets)

        # L_L: future structure (CPC or cosine)
        l_future = (
            self.future_loss(z, h)
            if z is not None
            else torch.tensor(0.0, device=dev)
        )

        # L_E: changepoint alignment
        l_changepoint = torch.tensor(0.0, device=dev)
        if self.lambda_changepoint > 0.0:
            l_changepoint = self.changepoint_loss(h, regime_probs)

        # L_r: regime diversity
        l_regime = self.regime_loss(regime_probs, regime_indices)

        # L_g: competitive gate
        l_competitive = torch.tensor(0.0, device=dev)
        if self.lambda_competitive > 0.0:
            l_competitive = self.competitive_gate_loss(z, h, gate_values)

        # L_m: memory focus (attention entropy if available, else variance)
        l_mem = self.memory_loss(mem_read, mem_attn)

        # Legacy manifest regularizer
        l_manifest = self.manifest_loss(gate_values)

        # Clamp every auxiliary loss to prevent backward OOM from runaway values
        l_future = _safe_loss(l_future)
        l_changepoint = _safe_loss(l_changepoint)
        l_regime = _safe_loss(l_regime)
        l_competitive = _safe_loss(l_competitive)
        l_mem = _safe_loss(l_mem)

        total = (
            l_tok
            + self.lambda_future * l_future
            + self.lambda_changepoint * l_changepoint
            + self.lambda_regime * l_regime
            + self.lambda_competitive * l_competitive
            + self.lambda_mem * l_mem
            + self.lambda_manifest * l_manifest
        )

        components = {
            "loss_tok": l_tok.item(),
            "loss_future": l_future.item(),
            "loss_changepoint": l_changepoint.item(),
            "loss_regime": l_regime.item(),
            "loss_competitive": l_competitive.item(),
            "loss_mem": l_mem.item(),
            "loss_manifest": l_manifest.item(),
            "loss_total": total.item(),
        }

        return total, components
