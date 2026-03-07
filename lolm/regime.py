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

"""Discrete regime / phase layer with Gumbel-Softmax.

Represents the model's current organizational mode:
exploration, synthesis, repair, planning, narrative, etc.

v2: MPST-inspired neighbor interaction — tokens influence nearby tokens'
regime choices through a causal conv1d, creating coherent regime segments
instead of independent per-token decisions.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class RegimeLayer(nn.Module):
    """Discrete regime state using Gumbel-Softmax.

    Takes concatenated [z; h; m] and produces a soft regime embedding.
    Temperature is annealed externally during training.

    With neighbor_interaction=True, regime logits are influenced by
    neighboring tokens' logits via a causal conv1d (MPST-style).
    This creates spatially coherent regime segments.
    """

    def __init__(self, d_input: int, n_codes: int = 16,
                 d_regime: int = 64, neighbor_interaction: bool = False,
                 neighbor_kernel_size: int = 5):
        super().__init__()
        self.n_codes = n_codes
        self.logit_proj = nn.Linear(d_input, n_codes, bias=False)
        self.codebook = nn.Embedding(n_codes, d_regime)

        # MPST neighbor interaction: causal conv1d over regime logits
        self.neighbor_interaction = neighbor_interaction
        if neighbor_interaction:
            # Causal conv: kernel only looks at current + past tokens
            self.neighbor_conv = nn.Conv1d(
                n_codes, n_codes, kernel_size=neighbor_kernel_size,
                padding=0, groups=1, bias=True,
            )
            self.neighbor_kernel_size = neighbor_kernel_size
            # Scale factor so neighbor influence doesn't overwhelm direct logits
            self.neighbor_scale = nn.Parameter(torch.tensor(0.1))

    def forward(self, z: torch.Tensor, h: torch.Tensor,
                m: torch.Tensor, temperature: float = 1.0
                ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Args:
            z: (B, T, d_z) latent state
            h: (B, T, d_h) decoder hidden
            m: (B, T, d_m) memory readout
            temperature: Gumbel-Softmax temperature
        Returns:
            r_embed: (B, T, d_regime) soft regime embedding
            probs: (B, T, n_codes) regime probabilities
            indices: (B, T) argmax regime indices
        """
        combined = torch.cat([z, h, m], dim=-1)
        logits = self.logit_proj(combined)  # (B, T, n_codes)

        # MPST: neighbor interaction via causal conv1d
        if self.neighbor_interaction:
            # Reshape for conv1d: (B, n_codes, T)
            logits_conv = logits.transpose(1, 2)
            # Causal padding: pad only on the left
            logits_padded = F.pad(logits_conv, (self.neighbor_kernel_size - 1, 0))
            neighbor_influence = self.neighbor_conv(logits_padded)  # (B, n_codes, T)
            neighbor_influence = neighbor_influence.transpose(1, 2)  # (B, T, n_codes)
            logits = logits + self.neighbor_scale * neighbor_influence

        if self.training:
            probs = F.gumbel_softmax(logits, tau=temperature, hard=False, dim=-1)
        else:
            probs = F.softmax(logits / max(temperature, 0.01), dim=-1)

        indices = probs.argmax(dim=-1)  # (B, T)

        # Soft embedding: weighted sum of codebook
        r_embed = torch.matmul(probs, self.codebook.weight)  # (B, T, d_regime)

        return r_embed, probs, indices
