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

"""Full LOLM model wiring all modules together.

token_ids -> SurfaceDecoder -> h
                                |-> LatentSSMCore -> z
                                |-> PersistentMemory -> m
                                |-> RegimeLayer(z, h, m) -> r_embed
                                |-> ManifestationGate(z, h, m, r) -> g
                                |-> fused = g*h + (1-g)*z + m + r
                                |-> LM Head -> logits
"""

from __future__ import annotations

import torch
import torch.nn as nn

from .config import ModelConfig
from .decoder import SurfaceDecoder
from .ssm import LatentSSMCore
from .memory import PersistentMemory
from .regime import RegimeLayer
from .gate import ManifestationGate


class LOLMOutput:
    """Container for model outputs."""
    __slots__ = ("logits", "h", "z", "mem_read", "regime_probs",
                 "regime_indices", "gate_values", "memory_state")

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class LOLM(nn.Module):
    """Latent Order Language Model.

    Language as manifestation of deeper latent order, not root cognition.
    """

    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        d = cfg.d_model

        # Surface decoder (always present)
        self.decoder = SurfaceDecoder(
            d_model=d, n_heads=cfg.n_heads, n_layers=cfg.n_layers,
            d_ff=cfg.d_ff, vocab_size=cfg.vocab_size,
            max_seq_len=cfg.max_seq_len, dropout=cfg.dropout,
        )

        # Latent SSM core
        self.ssm = None
        if cfg.ssm.enabled:
            self.ssm = LatentSSMCore(
                d_model=d, n_layers=cfg.ssm.n_layers,
                d_state=cfg.ssm.d_state, expand=cfg.ssm.expand,
                use_cuda_kernels=cfg.ssm.use_cuda_kernels,
            )

        # Persistent memory
        self.memory = None
        if cfg.memory.enabled:
            self.memory = PersistentMemory(
                n_slots=cfg.memory.n_slots, n_banks=cfg.memory.n_banks,
                slot_dim=cfg.memory.slot_dim, d_model=d,
            )

        # Regime layer
        self.regime = None
        if cfg.regime.enabled:
            # Input dim depends on what's available
            d_regime_in = d  # h is always present
            if cfg.ssm.enabled:
                d_regime_in += d  # z
            if cfg.memory.enabled:
                d_regime_in += d  # m
            self.regime = RegimeLayer(
                d_input=d_regime_in,
                n_codes=cfg.regime.n_codes,
                d_regime=cfg.regime.d_regime,
            )

        # Manifestation gate
        self.gate = None
        if cfg.gate.enabled and cfg.ssm.enabled:
            self.gate = ManifestationGate(d_model=d, d_regime=cfg.regime.d_regime)

        # Fusion projections for combining streams
        self.proj_z = nn.Linear(d, d, bias=False) if cfg.ssm.enabled else None
        self.proj_h = nn.Linear(d, d, bias=False)
        self.proj_m = nn.Linear(d, d, bias=False) if cfg.memory.enabled else None
        self.proj_r = nn.Linear(cfg.regime.d_regime, d, bias=False) if cfg.regime.enabled else None

        # LM head — weight-tied with token embedding
        self.lm_head = nn.Linear(d, cfg.vocab_size, bias=False)
        self.lm_head.weight = self.decoder.tok_emb.weight

    def forward(self, token_ids: torch.Tensor,
                memory_state: list[torch.Tensor] | None = None,
                regime_temperature: float = 1.0) -> LOLMOutput:
        """
        Args:
            token_ids: (B, T) input token ids
            memory_state: optional list of memory bank tensors
            regime_temperature: Gumbel-Softmax temperature
        Returns:
            LOLMOutput with logits and all intermediate states
        """
        B = token_ids.size(0)
        device = token_ids.device

        # 1. Surface decoder
        h = self.decoder(token_ids)  # (B, T, d)

        # 2. Latent SSM
        z = None
        if self.ssm is not None:
            z = self.ssm(h)  # (B, T, d)

        # 3. Memory
        mem_read = None
        new_memory_state = None
        if self.memory is not None:
            if memory_state is None:
                memory_state = self.memory.get_initial_memory(B, device)
            mem_read, new_memory_state = self.memory(h, memory_state)

        # 4. Regime layer
        regime_probs = None
        regime_indices = None
        r_embed = None
        if self.regime is not None:
            # Build regime input from available components
            r_z = z if z is not None else torch.zeros_like(h)
            r_m = mem_read if mem_read is not None else torch.zeros_like(h)
            r_embed, regime_probs, regime_indices = self.regime(
                r_z, h, r_m, temperature=regime_temperature
            )

        # 5. Manifestation gate + fusion
        gate_values = None
        if self.gate is not None and z is not None:
            g_m = mem_read if mem_read is not None else torch.zeros_like(h)
            g_r = r_embed if r_embed is not None else torch.zeros(
                *h.shape[:2], self.cfg.regime.d_regime, device=device
            )
            gate_values = self.gate(z, h, g_m, g_r)  # (B, T, d)

            # Gated fusion: g*h + (1-g)*z
            fused = gate_values * self.proj_h(h) + (1 - gate_values) * self.proj_z(z)
        else:
            # No gate: just use h (plain decoder mode)
            fused = self.proj_h(h)
            if z is not None and self.proj_z is not None:
                fused = fused + self.proj_z(z)

        # Add memory and regime contributions
        if mem_read is not None and self.proj_m is not None:
            fused = fused + self.proj_m(mem_read)
        if r_embed is not None and self.proj_r is not None:
            fused = fused + self.proj_r(r_embed)

        # 6. LM head
        logits = self.lm_head(fused)  # (B, T, vocab_size)

        return LOLMOutput(
            logits=logits,
            h=h,
            z=z,
            mem_read=mem_read,
            regime_probs=regime_probs,
            regime_indices=regime_indices,
            gate_values=gate_values,
            memory_state=new_memory_state,
        )

    def count_parameters(self) -> dict[str, int]:
        """Count parameters by component."""
        counts = {}
        counts["decoder"] = sum(p.numel() for p in self.decoder.parameters())
        if self.ssm:
            counts["ssm"] = sum(p.numel() for p in self.ssm.parameters())
        if self.memory:
            counts["memory"] = sum(p.numel() for p in self.memory.parameters())
        if self.regime:
            counts["regime"] = sum(p.numel() for p in self.regime.parameters())
        if self.gate:
            counts["gate"] = sum(p.numel() for p in self.gate.parameters())

        # Fusion projections
        fusion_params = sum(
            p.numel() for name, p in self.named_parameters()
            if name.startswith("proj_")
        )
        counts["fusion"] = fusion_params

        # LM head is tied, don't double-count
        counts["lm_head"] = 0  # tied with decoder.tok_emb

        counts["total"] = sum(p.numel() for p in self.parameters())
        return counts
