# Copyright 2026 Bryan Leonard & Brandyn Leonard
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Manifestation gate for surface/latent arbitration.

Controls when latent structure should become externalized in language.
g ~ 1: surface decoder drives output (standard LM behavior)
g ~ 0: latent state drives output (latent-order behavior)

v2: Biased initialization to start off-center (not 0.5 coin-flip).
"""

import torch
import torch.nn as nn


class ManifestationGate(nn.Module):
    """2-layer MLP producing per-dimension gating in [0, 1].

    Decides how much of the output comes from the surface decoder (h)
    vs the latent state (z), conditioned on regime and memory.

    Args:
        d_model: Model dimension
        d_regime: Regime embedding dimension
        init_bias: Bias for gate initialization. Negative = start latent-preferring
                   (gate < 0.5), positive = start surface-preferring (gate > 0.5).
                   Default 0.0 = start at 0.5. Recommended: -0.5 to start at ~0.38.
    """

    def __init__(self, d_model: int, d_regime: int, init_bias: float = 0.0):
        super().__init__()
        d_input = d_model * 3 + d_regime  # z + h + m + r_embed
        d_hidden = d_model * 2
        self.fc1 = nn.Linear(d_input, d_hidden, bias=False)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(d_hidden, d_model, bias=True)
        self.sigmoid = nn.Sigmoid()

        # Bias initialization: shift the gate output away from 0.5
        if init_bias != 0.0:
            nn.init.constant_(self.fc2.bias, init_bias)

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
        return self.sigmoid(self.fc2(self.act(self.fc1(combined))))
