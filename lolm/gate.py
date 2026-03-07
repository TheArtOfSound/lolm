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

"""Manifestation gate — the NFET core.

Controls when latent structure should become externalized in language.
g ~ 1: surface decoder drives output (standard LM behavior)
g ~ 0: latent state drives output (novel latent-order behavior)
"""

import torch
import torch.nn as nn


class ManifestationGate(nn.Module):
    """2-layer MLP producing per-dimension gating in [0, 1].

    Decides how much of the output comes from the surface decoder (h)
    vs the latent order field (z), conditioned on regime and memory.
    """

    def __init__(self, d_model: int, d_regime: int):
        super().__init__()
        d_input = d_model * 3 + d_regime  # z + h + m + r_embed
        d_hidden = d_model * 2
        self.net = nn.Sequential(
            nn.Linear(d_input, d_hidden, bias=False),
            nn.GELU(),
            nn.Linear(d_hidden, d_model, bias=True),
            nn.Sigmoid(),
        )

    def forward(self, z: torch.Tensor, h: torch.Tensor,
                m: torch.Tensor, r_embed: torch.Tensor) -> torch.Tensor:
        """
        Args:
            z: (B, T, d_model) latent state
            h: (B, T, d_model) decoder hidden
            m: (B, T, d_model) memory readout
            r_embed: (B, T, d_regime) regime embedding
        Returns:
            g: (B, T, d_model) gate values in [0, 1]
        """
        combined = torch.cat([z, h, m, r_embed], dim=-1)
        return self.net(combined)
