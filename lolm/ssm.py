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

"""Selective State-Space Model (Mamba-style) latent core.

Three scan backends:
  1. mamba-ssm CUDA kernels (fastest, requires mamba-ssm package)
  2. Parallel associative scan in pure PyTorch (fast on GPU, no extra deps)
  3. Sequential scan (fallback for MPS / CPU)

This is the latent order field z_t that evolves underneath the surface decoder.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint as grad_checkpoint

# Try to import mamba-ssm CUDA kernels (available on GPU)
_MAMBA_CUDA_AVAILABLE = False
try:
    from mamba_ssm import Mamba as MambaCuda
    _MAMBA_CUDA_AVAILABLE = True
except ImportError:
    pass


def _parallel_scan_simple(A_bar: torch.Tensor, Bx: torch.Tensor) -> torch.Tensor:
    """Simple parallel prefix scan using doubling (Hillis-Steele style).

    Simpler than Blelloch, uses O(T log T) work but O(log T) depth.
    On GPU, the extra work is cheap since all operations are parallel.

    Args:
        A_bar: (B, T, D, N) - discretized state transition
        Bx:    (B, T, D, N) - discretized input

    Returns:
        H: (B, T, D, N) - hidden states for all timesteps
    """
    # Start: h_t = Bx_t (will accumulate via scan)
    h = Bx.clone()
    a = A_bar.clone()

    T = A_bar.shape[1]
    stride = 1

    while stride < T:
        # For positions >= stride, combine with position (pos - stride)
        h_shifted = F.pad(h[:, :-stride], (0, 0, 0, 0, stride, 0))
        a_shifted = F.pad(a[:, :-stride], (0, 0, 0, 0, stride, 0), value=1.0)

        # New h[t] = a[t] * h[t-stride] + h[t]  (for t >= stride)
        # New a[t] = a[t] * a[t-stride]
        h_new = a * h_shifted + h
        a_new = a * a_shifted

        # Only update positions >= stride
        mask = torch.zeros(T, device=h.device, dtype=torch.bool)
        mask[stride:] = True

        h = torch.where(mask[None, :, None, None], h_new, h)
        a = torch.where(mask[None, :, None, None], a_new, a)

        stride *= 2

    return h


class CudaSSMLayer(nn.Module):
    """Mamba layer using official CUDA kernels. Much faster than pure PyTorch."""

    def __init__(self, d_model: int, d_state: int = 16, expand: int = 2):
        super().__init__()
        self.mamba = MambaCuda(
            d_model=d_model,
            d_state=d_state,
            expand=expand,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.mamba(x)


class SelectiveSSMLayer(nn.Module):
    """Single selective SSM layer with input-dependent dynamics."""

    def __init__(self, d_model: int, d_state: int = 16, expand: int = 2):
        super().__init__()
        self.d_inner = d_model * expand
        self.d_state = d_state

        # Input projection: expand to d_inner
        self.in_proj = nn.Linear(d_model, self.d_inner * 2, bias=False)

        # Selective parameters: input-dependent dt, B, C
        self.dt_proj = nn.Linear(self.d_inner, self.d_inner, bias=True)
        self.B_proj = nn.Linear(self.d_inner, d_state, bias=False)
        self.C_proj = nn.Linear(self.d_inner, d_state, bias=False)

        # Diagonal A in log-space (learned)
        self.A_log = nn.Parameter(torch.log(torch.arange(1, d_state + 1, dtype=torch.float32)).unsqueeze(0).expand(self.d_inner, -1))

        # D skip connection
        self.D = nn.Parameter(torch.ones(self.d_inner))

        # Output projection
        self.out_proj = nn.Linear(self.d_inner, d_model, bias=False)
        self.ln = nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (B, T, d_model) input (projected from h_t and/or e_t)
        Returns:
            z: (B, T, d_model) latent state sequence
        """
        B, T, _ = x.shape
        residual = x

        # Project and split into main path + gate
        xz = self.in_proj(x)
        x_main, z_gate = xz.chunk(2, dim=-1)  # each (B, T, d_inner)

        # Selective parameters
        A = -torch.exp(self.A_log)  # (d_inner, d_state), negative for stability
        dt = F.softplus(self.dt_proj(x_main))  # (B, T, d_inner)
        B_t = self.B_proj(x_main)  # (B, T, d_state)
        C_t = self.C_proj(x_main)  # (B, T, d_state)

        # Discretize: A_bar = exp(dt * A), B_bar = dt * B
        # dt: (B, T, d_inner) -> (B, T, d_inner, 1)
        # A: (d_inner, d_state)
        dt_expanded = dt.unsqueeze(-1)  # (B, T, d_inner, 1)
        A_bar = torch.exp(dt_expanded * A)  # (B, T, d_inner, d_state)
        B_bar = dt_expanded * B_t.unsqueeze(2)  # (B, T, d_inner, d_state)

        # Scan: compute h[t] = A_bar[t] * h[t-1] + B_bar[t] * x[t] for all t
        Bx = B_bar * x_main.unsqueeze(-1)  # (B, T, d_inner, d_state)

        if x.device.type == 'cuda':
            # Parallel scan: O(log T) depth, massive GPU speedup
            H = _parallel_scan_simple(A_bar, Bx)  # (B, T, d_inner, d_state)
        else:
            # Sequential scan for MPS/CPU (parallel scan has overhead on non-GPU)
            h = torch.zeros(B, self.d_inner, self.d_state, device=x.device, dtype=x.dtype)
            hs = []
            for t in range(T):
                h = A_bar[:, t] * h + Bx[:, t]
                hs.append(h)
            H = torch.stack(hs, dim=1)  # (B, T, d_inner, d_state)

        # Output: y[t] = C[t] . h[t]
        y = (H * C_t.unsqueeze(2)).sum(dim=-1)  # (B, T, d_inner)

        # Gate and skip
        y = y * F.silu(z_gate)
        y = y + x_main * self.D  # skip connection

        # Project back
        out = self.out_proj(y)
        return self.ln(out + residual)


class LatentSSMCore(nn.Module):
    """Multi-layer selective SSM forming the latent order field.

    Takes projected decoder hidden states and evolves a continuous
    latent representation z_t that tracks slow semantic drift,
    unresolved intent, and plan structure.
    """

    def __init__(self, d_model: int, n_layers: int = 2,
                 d_state: int = 16, expand: int = 2,
                 use_cuda_kernels: bool = False):
        super().__init__()
        self.proj_in = nn.Linear(d_model, d_model, bias=False)

        use_cuda = use_cuda_kernels and _MAMBA_CUDA_AVAILABLE
        LayerClass = CudaSSMLayer if use_cuda else SelectiveSSMLayer
        if use_cuda:
            print("SSM: using mamba-ssm CUDA kernels")
        else:
            print("SSM: using pure PyTorch parallel scan (GPU) / sequential scan (CPU/MPS)")

        self.layers = nn.ModuleList([
            LayerClass(d_model, d_state, expand)
            for _ in range(n_layers)
        ])

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        """
        Args:
            h: (B, T, d_model) hidden state from surface decoder
        Returns:
            z: (B, T, d_model) latent order field
        """
        z = self.proj_in(h)
        for layer in self.layers:
            if getattr(self, "use_gradient_checkpoint", False) and self.training:
                z = grad_checkpoint(layer, z, use_reentrant=False)
            else:
                z = layer(z)
        return z
