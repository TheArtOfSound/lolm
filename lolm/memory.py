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

from __future__ import annotations

"""Persistent memory with 3 banks: episodic, semantic, self.

Provides read (attention-based retrieval) and gated write operations.

v3: Chunked intra-sequence processing — splits the sequence into chunks
and chains write→read across chunks, so the write path gets gradients.
Previously the write output was returned but never consumed by any
loss-connected computation, leaving all write parameters (write_proj,
forget_gate, write_gate) with grad=NONE since step 0.
"""

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

    def read(self, query: torch.Tensor, memory: torch.Tensor
             ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            query: (B, T, d_model)
            memory: (B, n_slots, slot_dim)
        Returns:
            retrieved: (B, T, slot_dim)
            attn: (B, T, n_slots) — attention weights for entropy loss
        """
        q = self.query_proj(query)  # (B, T, slot_dim)
        # Attention over memory slots
        attn = torch.matmul(q, memory.transpose(-1, -2))  # (B, T, n_slots)
        attn = attn / (self.slot_dim ** 0.5)
        # Upcast to float32 for softmax to prevent bfloat16 NaN
        attn = F.softmax(attn.float(), dim=-1).to(q.dtype)
        return torch.matmul(attn, memory), attn  # (B, T, slot_dim), (B, T, n_slots)

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

    def _read_write_step(self, h_chunk: torch.Tensor,
                         memory_state: list[torch.Tensor]
                         ) -> tuple[torch.Tensor, list[torch.Tensor], torch.Tensor]:
        """Single read+write step for one chunk of the sequence."""
        reads = []
        attns = []
        new_states = []
        for bank, m in zip(self.banks, memory_state):
            read_out, attn = bank.read(h_chunk, m)
            reads.append(read_out)
            attns.append(attn)
            new_states.append(bank.write(h_chunk, m))
        combined = torch.cat(reads, dim=-1)
        mem_read = self.combine(combined)
        # Average attention across banks: (B, T, n_slots)
        mem_attn = torch.stack(attns, dim=0).mean(dim=0)
        return mem_read, new_states, mem_attn

    def forward(self, h: torch.Tensor,
                memory_state: list[torch.Tensor],
                n_chunks: int = 1) -> tuple[torch.Tensor, list[torch.Tensor], torch.Tensor]:
        """
        Args:
            h: (B, T, d_model) hidden state
            memory_state: list of (B, n_slots, slot_dim) per bank
            n_chunks: if >1, split sequence into chunks and chain
                      write→read across chunks so write path gets gradients.
                      Gradient path: loss → read(chunk_j) → memory_j-1
                      → write(chunk_j-1) → write_proj/forget_gate/write_gate
        Returns:
            mem_read: (B, T, d_model) combined memory readout
            new_memory_state: updated memory state
            mem_attn: (B, T, n_slots) attention weights (avg over banks)
        """
        if n_chunks <= 1:
            return self._read_write_step(h, memory_state)

        # Chunked processing: write at chunk i feeds read at chunk i+1
        T = h.size(1)
        chunk_size = T // n_chunks
        all_mem_reads = []
        all_mem_attns = []
        current_memory = memory_state

        for i in range(n_chunks):
            start = i * chunk_size
            end = T if i == n_chunks - 1 else (i + 1) * chunk_size
            h_chunk = h[:, start:end]

            mem_read_chunk, new_memory, mem_attn_chunk = self._read_write_step(
                h_chunk, current_memory
            )
            all_mem_reads.append(mem_read_chunk)
            all_mem_attns.append(mem_attn_chunk)

            # Updated memory flows to next chunk's read — gradient bridge
            current_memory = new_memory

        mem_read = torch.cat(all_mem_reads, dim=1)  # (B, T, d_model)
        mem_attn = torch.cat(all_mem_attns, dim=1)  # (B, T, n_slots)
        return mem_read, current_memory, mem_attn
