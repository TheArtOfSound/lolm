# Copyright 2026 Bryan Leonard & Brandyn Leonard
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rotary Positional Encoding (RoPE) for the surface decoder."""

import torch


def precompute_freqs(dim: int, max_seq_len: int, theta: float = 10000.0) -> torch.Tensor:
    """Precompute complex exponential frequencies for RoPE.

    Returns: (max_seq_len, dim//2) complex tensor.
    """
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
    t = torch.arange(max_seq_len, dtype=torch.float32)
    freqs = torch.outer(t, freqs)
    return torch.polar(torch.ones_like(freqs), freqs)


def apply_rope(x: torch.Tensor, freqs: torch.Tensor) -> torch.Tensor:
    """Apply rotary embeddings to input tensor.

    Args:
        x: (B, n_heads, T, head_dim)
        freqs: (T, head_dim//2) complex
    Returns:
        Rotated tensor, same shape as x.
    """
    # Reshape to pairs: (B, n_heads, T, head_dim//2, 2)
    x_pairs = x.float().reshape(*x.shape[:-1], -1, 2)
    # Convert to complex
    x_complex = torch.view_as_complex(x_pairs)
    # Apply rotation
    freqs = freqs.unsqueeze(0).unsqueeze(0)  # (1, 1, T, head_dim//2)
    x_rotated = x_complex * freqs
    # Back to real
    x_out = torch.view_as_real(x_rotated).reshape(*x.shape)
    return x_out.type_as(x)
