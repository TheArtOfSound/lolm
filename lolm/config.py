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

"""Configuration dataclasses and YAML loader for LOLM."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class SSMConfig:
    enabled: bool = True
    n_layers: int = 2
    d_state: int = 16
    expand: int = 2
    use_cuda_kernels: bool = False


@dataclass
class RegimeConfig:
    enabled: bool = True
    n_codes: int = 16
    d_regime: int = 64
    temp_start: float = 1.0
    temp_end: float = 0.1
    temp_anneal_steps: int = 50000
    # MPST neighbor interaction (conv1d over regime logits)
    neighbor_interaction: bool = False
    neighbor_kernel_size: int = 5


@dataclass
class MemoryConfig:
    enabled: bool = True
    n_slots: int = 32
    n_banks: int = 3
    slot_dim: int = 256
    n_chunks: int = 1  # >1 splits sequence into chunks, chaining write→read for gradients


@dataclass
class GateConfig:
    enabled: bool = True
    # Initialization bias: negative = latent-preferring, positive = surface-preferring
    init_bias: float = 0.0
    # Normalize branches before gating (LayerNorm on h and z)
    normalize_branches: bool = False


@dataclass
class ModelConfig:
    d_model: int = 256
    n_heads: int = 8
    n_layers: int = 6
    d_ff: int = 1024
    vocab_size: int = 50257
    max_seq_len: int = 512
    dropout: float = 0.1
    ssm: SSMConfig = field(default_factory=SSMConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    gate: GateConfig = field(default_factory=GateConfig)


@dataclass
class TrainingConfig:
    batch_size: int = 4
    seq_len: int = 512
    max_steps: int = 100000
    lr: float = 3e-4
    weight_decay: float = 0.1
    beta1: float = 0.9
    beta2: float = 0.95
    warmup_steps: int = 1000
    grad_clip: float = 1.0
    device: str = "mps"
    dtype: str = "float32"
    log_interval: int = 100
    eval_interval: int = 1000
    save_interval: int = 5000
    cache_clear_interval: int = 100
    grad_accumulation_steps: int = 1
    compile: bool = False


@dataclass
class LossConfig:
    lambda_future: float = 0.1
    lambda_regime: float = 0.05
    lambda_mem: float = 0.05
    lambda_manifest: float = 0.01
    future_window: int = 8
    # Load-balancing loss for regime (MoE-style, prevents collapse)
    lambda_balance: float = 0.1
    use_load_balance: bool = False
    # Sticky transition penalty: penalize regime switches between adjacent tokens
    lambda_sticky: float = 0.0


@dataclass
class DataConfig:
    dataset: str = "roneneldan/TinyStories"
    tokenizer: str = "gpt2"
    cache_dir: str = "./data"
    streaming: bool = False


@dataclass
class LOLMConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    loss: LossConfig = field(default_factory=LossConfig)
    data: DataConfig = field(default_factory=DataConfig)


def _dict_to_dataclass(cls, d: dict):
    """Recursively convert a dict to a dataclass, ignoring unknown keys."""
    if not isinstance(d, dict):
        return d
    fields = {f.name: f for f in cls.__dataclass_fields__.values()}
    kwargs = {}
    for k, v in d.items():
        if k not in fields:
            continue
        ft = fields[k].type
        if hasattr(ft, "__dataclass_fields__"):
            kwargs[k] = _dict_to_dataclass(ft, v)
        else:
            kwargs[k] = v
    return cls(**kwargs)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively."""
    merged = base.copy()
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(path: str) -> LOLMConfig:
    """Load config from YAML, resolving _base_ inheritance."""
    p = Path(path)
    with open(p) as f:
        raw = yaml.safe_load(f)

    if "_base_" in raw:
        base_path = (p.parent / raw.pop("_base_")).resolve()
        base_cfg = load_config(str(base_path))
        # Convert base to dict, merge, reconstruct
        import dataclasses
        base_dict = dataclasses.asdict(base_cfg)
        merged = _deep_merge(base_dict, raw)
        return _dict_to_dataclass(LOLMConfig, merged)

    return _dict_to_dataclass(LOLMConfig, raw)
