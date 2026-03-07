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

Pure PyTorch sequential scan for MPS, with optional mamba-ssm CUDA kernels.
This is the latent order field z_t that evolves underneath the surface decoder.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

# Try to import mamba-ssm CUDA kernels (available on GPU)
_MAMBA_CUDA_AVAILABLE = False
try:
    from mamba_ssm import Mamba as MambaCuda
    _MAMBA_CUDA_AVAILABLE = True
except ImportError:
    pass


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

        # Sequential scan
        h = torch.zeros(B, self.d_inner, self.d_state, device=x.device, dtype=x.dtype)
        ys = []
        for t in range(T):
            h = A_bar[:, t] * h + B_bar[:, t] * x_main[:, t].unsqueeze(-1)
            y_t = (h * C_t[:, t].unsqueeze(1)).sum(dim=-1)  # (B, d_inner)
            ys.append(y_t)

        y = torch.stack(ys, dim=1)  # (B, T, d_inner)

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
            print("SSM: using pure PyTorch sequential scan")

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
            z = layer(z)
        return z
