# Copyright 2026 Bryan Leonard
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Five-objective loss for LOLM training.

L = L_tok + λ_f·L_future + λ_r·L_regime + λ_m·L_mem + λ_g·L_manifest
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class LOLMLoss(nn.Module):
    """Multi-objective loss combining token prediction with latent supervision."""

    def __init__(self, lambda_future: float = 0.1, lambda_regime: float = 0.05,
                 lambda_mem: float = 0.05, lambda_manifest: float = 0.01,
                 future_window: int = 8, lambda_balance: float = 0.1,
                 use_load_balance: bool = False, lambda_sticky: float = 0.0):
        super().__init__()
        self.lambda_future = lambda_future
        self.lambda_regime = lambda_regime
        self.lambda_mem = lambda_mem
        self.lambda_manifest = lambda_manifest
        self.future_window = future_window
        self.lambda_balance = lambda_balance
        self.use_load_balance = use_load_balance
        self.lambda_sticky = lambda_sticky

        # Learned future summary projection (z -> predicted future embedding)
        self.future_proj = None  # Initialized lazily based on d_model

    def _init_future_proj(self, d_model: int, device: torch.device):
        if self.future_proj is None:
            self.future_proj = nn.Linear(d_model, d_model, bias=False).to(device)

    def token_loss(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """Standard next-token cross-entropy.

        Args:
            logits: (B, T, vocab_size)
            targets: (B, T) token ids
        """
        return F.cross_entropy(
            logits.view(-1, logits.size(-1)),
            targets.view(-1),
            ignore_index=-1,
        )

    def future_loss(self, z: torch.Tensor, h: torch.Tensor) -> torch.Tensor:
        """Force z_t to predict summary of future hidden states.

        Uses cosine similarity between projected z_t and mean of
        h_{t+1:t+k} (detached to prevent gradient leaking back).

        Args:
            z: (B, T, d_model) latent state
            h: (B, T, d_model) decoder hidden state
        """
        if z is None:
            return torch.tensor(0.0, device=h.device)

        self._init_future_proj(z.size(-1), z.device)

        B, T, D = h.shape
        k = self.future_window

        if T <= k:
            return torch.tensor(0.0, device=h.device)

        # Future summary: mean of next k hidden states (detached)
        # For each position t, compute mean(h[t+1:t+k+1])
        # Use unfolded view for efficiency
        h_padded = F.pad(h, (0, 0, 0, k), value=0.0)  # (B, T+k, D)
        # Cumulative sum trick for windowed mean
        h_cumsum = h_padded.cumsum(dim=1)  # (B, T+k, D)
        future_sum = h_cumsum[:, k:T+k] - h_cumsum[:, :T]  # (B, T, D)
        future_mean = future_sum / k

        # Only compute loss for positions where full window exists
        valid = T - k
        if valid <= 0:
            return torch.tensor(0.0, device=h.device)

        z_proj = self.future_proj(z[:, :valid])  # (B, valid, D)
        target = future_mean[:, :valid].detach()  # (B, valid, D)

        # Negative cosine similarity (minimize = maximize similarity)
        cos_sim = F.cosine_similarity(z_proj, target, dim=-1)  # (B, valid)
        return -cos_sim.mean()

    def regime_loss(self, probs: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
        """Regime diversity loss — prevents collapse to a single code.

        Two modes:
        - load_balance=True (new): MoE-style load-balancing + entropy maximization
        - load_balance=False (legacy): entropy minimization (causes collapse!)

        Args:
            probs: (B, T, n_codes) regime probabilities
            indices: (B, T) argmax regime indices
        """
        if probs is None:
            return torch.tensor(0.0, device=indices.device if indices is not None else "cpu")

        if self.use_load_balance:
            return self._load_balance_loss(probs)
        else:
            # Legacy behavior (KNOWN TO CAUSE COLLAPSE)
            entropy = -(probs * (probs + 1e-8).log()).sum(dim=-1).mean()
            if indices.size(1) > 1:
                switches = (indices[:, 1:] != indices[:, :-1]).float().mean()
            else:
                switches = torch.tensor(0.0, device=probs.device)
            return entropy + 0.1 * switches

    def _load_balance_loss(self, probs: torch.Tensor) -> torch.Tensor:
        """MoE-style load-balancing loss + entropy maximization + sticky transitions.

        Three components:
        1. Load balancing — penalize unequal code usage across batch
        2. Entropy maximization — encourage per-token exploration
        3. Sticky transitions — penalize regime switches between adjacent tokens
           (encourages coherent regime segments, not per-token noise)

        Based on Switch Transformer / GShard load-balancing approach.

        Args:
            probs: (B, T, n_codes) regime probabilities
        """
        n_codes = probs.size(-1)

        # 1. Load-balancing: penalize when codes have unequal usage
        code_freq = probs.mean(dim=(0, 1))  # (n_codes,)
        hard_assign = F.one_hot(probs.argmax(dim=-1), n_codes).float()
        route_freq = hard_assign.mean(dim=(0, 1))  # (n_codes,)
        balance_loss = n_codes * (code_freq * route_freq).sum()

        # 2. Entropy maximization: encourage per-token exploration
        per_token_entropy = -(probs * (probs + 1e-8).log()).sum(dim=-1).mean()
        neg_entropy = -per_token_entropy  # Minimize this = maximize entropy

        # 3. Sticky transitions: encourage adjacent tokens to use same regime
        # Uses differentiable cosine similarity between adjacent prob vectors
        sticky_loss = torch.tensor(0.0, device=probs.device)
        if self.lambda_sticky > 0.0 and probs.size(1) > 1:
            sim = F.cosine_similarity(probs[:, 1:], probs[:, :-1], dim=-1)
            sticky_loss = -sim.mean()  # Minimize = maximize similarity

        return (self.lambda_balance * balance_loss
                + neg_entropy
                + self.lambda_sticky * sticky_loss)

    def memory_loss(self, mem_read: torch.Tensor) -> torch.Tensor:
        """Encourage focused memory reads (low attention entropy).

        A proxy: penalize uniform-looking readouts via variance.
        Higher variance = more focused retrieval.

        Args:
            mem_read: (B, T, d_model) memory readout
        """
        if mem_read is None:
            return torch.tensor(0.0)

        # Encourage non-uniform reads (higher variance is better)
        var = mem_read.var(dim=-1).mean()
        return -var  # Minimize negative variance = maximize variance

    def manifest_loss(self, gate_values: torch.Tensor) -> torch.Tensor:
        """Penalize unnecessary externalization.

        Encourages gate to stay low (latent) unless useful.

        Args:
            gate_values: (B, T, d_model) in [0, 1]
        """
        if gate_values is None:
            return torch.tensor(0.0)

        return gate_values.mean()

    def forward(self, logits: torch.Tensor, targets: torch.Tensor,
                z: torch.Tensor = None, h: torch.Tensor = None,
                regime_probs: torch.Tensor = None,
                regime_indices: torch.Tensor = None,
                mem_read: torch.Tensor = None,
                gate_values: torch.Tensor = None) -> tuple[torch.Tensor, dict]:
        """Compute total loss and component breakdown.

        Returns:
            total_loss: scalar
            components: dict of individual loss values (detached)
        """
        l_tok = self.token_loss(logits, targets)
        l_future = self.future_loss(z, h) if z is not None else torch.tensor(0.0, device=logits.device)
        l_regime = self.regime_loss(regime_probs, regime_indices)
        l_mem = self.memory_loss(mem_read)
        l_manifest = self.manifest_loss(gate_values)

        total = (
            l_tok
            + self.lambda_future * l_future
            + self.lambda_regime * l_regime
            + self.lambda_mem * l_mem
            + self.lambda_manifest * l_manifest
        )

        components = {
            "loss_tok": l_tok.item(),
            "loss_future": l_future.item(),
            "loss_regime": l_regime.item(),
            "loss_mem": l_mem.item(),
            "loss_manifest": l_manifest.item(),
            "loss_total": total.item(),
        }

        return total, components
