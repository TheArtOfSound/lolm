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

"""Persistent memory with 3 banks: episodic, semantic, self.

Provides read (attention-based retrieval) and gated write operations.
Memory state persists across forward calls within a batch but is
reset between sequences during training.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class MemoryBank(nn.Module):
    """Single memory bank with attention read and gated write."""

    def __init__(self, n_slots: int, slot_dim: int, d_model: int):
        super().__init__()
        self.n_slots = n_slots
        self.slot_dim = slot_dim

        # Learnable initial memory
        self.init_memory = nn.Parameter(torch.randn(n_slots, slot_dim) * 0.02)

        # Read: query projection + attention
        self.query_proj = nn.Linear(d_model, slot_dim, bias=False)

        # Write: content + gate
        self.write_proj = nn.Linear(d_model, slot_dim, bias=False)
        self.forget_gate = nn.Linear(d_model, n_slots, bias=True)
        self.write_gate = nn.Linear(d_model, n_slots, bias=True)

    def read(self, query: torch.Tensor, memory: torch.Tensor) -> torch.Tensor:
        """
        Args:
            query: (B, T, d_model)
            memory: (B, n_slots, slot_dim)
        Returns:
            retrieved: (B, T, slot_dim)
        """
        q = self.query_proj(query)  # (B, T, slot_dim)
        # Attention over memory slots
        attn = torch.matmul(q, memory.transpose(-1, -2))  # (B, T, n_slots)
        attn = attn / (self.slot_dim ** 0.5)
        attn = F.softmax(attn, dim=-1)
        return torch.matmul(attn, memory)  # (B, T, slot_dim)

    def write(self, h: torch.Tensor, memory: torch.Tensor) -> torch.Tensor:
        """Gated write: aggregate over sequence, then update slots.

        Args:
            h: (B, T, d_model)
            memory: (B, n_slots, slot_dim)
        Returns:
            updated_memory: (B, n_slots, slot_dim)
        """
        # Aggregate write signal over sequence
        h_agg = h.mean(dim=1)  # (B, d_model)

        # Forget and write gates
        alpha = torch.sigmoid(self.forget_gate(h_agg)).unsqueeze(-1)  # (B, n_slots, 1)
        beta = torch.sigmoid(self.write_gate(h_agg)).unsqueeze(-1)  # (B, n_slots, 1)

        # Write content (broadcast to all slots, gated per-slot)
        content = self.write_proj(h_agg).unsqueeze(1)  # (B, 1, slot_dim)

        return alpha * memory + beta * content


class PersistentMemory(nn.Module):
    """Three-bank persistent memory: episodic, semantic, self.

    Each bank has independent read/write dynamics.
    Combined output is projected to d_model.
    """

    def __init__(self, n_slots: int = 32, n_banks: int = 3,
                 slot_dim: int = 256, d_model: int = 256):
        super().__init__()
        self.n_banks = n_banks
        self.banks = nn.ModuleList([
            MemoryBank(n_slots, slot_dim, d_model)
            for _ in range(n_banks)
        ])
        # Combine all bank reads into d_model
        self.combine = nn.Linear(slot_dim * n_banks, d_model, bias=False)

    def get_initial_memory(self, batch_size: int, device: torch.device) -> list[torch.Tensor]:
        """Get initial memory state for all banks."""
        return [
            bank.init_memory.unsqueeze(0).expand(batch_size, -1, -1).clone()
            for bank in self.banks
        ]

    def forward(self, h: torch.Tensor,
                memory_state: list[torch.Tensor]) -> tuple[torch.Tensor, list[torch.Tensor]]:
        """
        Args:
            h: (B, T, d_model) hidden state
            memory_state: list of (B, n_slots, slot_dim) per bank
        Returns:
            mem_read: (B, T, d_model) combined memory readout
            new_memory_state: updated memory state
        """
        reads = []
        new_states = []
        for bank, m in zip(self.banks, memory_state):
            reads.append(bank.read(h, m))
            new_states.append(bank.write(h, m))

        # Concatenate reads and project
        combined = torch.cat(reads, dim=-1)  # (B, T, slot_dim * n_banks)
        mem_read = self.combine(combined)  # (B, T, d_model)
        return mem_read, new_states
