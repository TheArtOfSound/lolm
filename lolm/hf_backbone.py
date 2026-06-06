"""Frozen Hugging Face causal-LM backbone wrapper.

This is the bridge between pretrained open checkpoints and LOLM-NFET grafts.
It loads a selected HF profile, freezes the base model by default, exposes
hidden states, and leaves all trainable capacity in the graft/controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import torch
import torch.nn as nn
from transformers import AutoModelForCausalLM, AutoTokenizer

from lolm.hf_registry import HFModelProfile, HFRegistry


_DTYPE_MAP = {
    "auto": None,
    "float32": torch.float32,
    "fp32": torch.float32,
    "float16": torch.float16,
    "fp16": torch.float16,
    "bfloat16": torch.bfloat16,
    "bf16": torch.bfloat16,
}


@dataclass
class HFBackboneOutput:
    logits: torch.Tensor
    hidden_states: torch.Tensor
    raw: Any


class FrozenHFBackbone(nn.Module):
    """HF causal LM loaded as a frozen feature backbone."""

    def __init__(
        self,
        profile: HFModelProfile,
        freeze: bool = True,
        output_hidden_states: bool = True,
    ) -> None:
        super().__init__()
        self.profile = profile
        self.tokenizer = AutoTokenizer.from_pretrained(
            profile.tokenizer_id,
            trust_remote_code=profile.trust_remote_code,
        )
        dtype = _DTYPE_MAP.get(profile.dtype, None)
        model_kwargs: Dict[str, Any] = {
            "trust_remote_code": profile.trust_remote_code,
            "output_hidden_states": output_hidden_states,
        }
        if dtype is not None:
            model_kwargs["torch_dtype"] = dtype
        if profile.device_map:
            model_kwargs["device_map"] = profile.device_map

        self.model = AutoModelForCausalLM.from_pretrained(profile.model_id, **model_kwargs)
        self.hidden_size = int(getattr(self.model.config, "hidden_size", 0) or getattr(self.model.config, "n_embd", 0))
        if self.hidden_size <= 0:
            raise ValueError(f"Could not infer hidden size for {profile.model_id}")

        if freeze:
            self.freeze()

    @classmethod
    def from_registry(
        cls,
        profile_name: Optional[str] = None,
        registry_path: str = "configs/hf_models.yaml",
        freeze: bool = True,
    ) -> "FrozenHFBackbone":
        registry = HFRegistry.load(registry_path)
        return cls(registry.get(profile_name), freeze=freeze)

    def freeze(self) -> None:
        for param in self.model.parameters():
            param.requires_grad_(False)
        self.model.eval()

    def unfreeze_last_layers(self, n_layers: int) -> None:
        """Optionally unfreeze the last N transformer layers for later experiments.

        Different HF families use different attribute names. This method supports
        common decoder stacks and fails loudly for unknown layouts.
        """
        candidate_paths = [
            ("model", "layers"),
            ("transformer", "h"),
            ("gpt_neox", "layers"),
        ]
        layers = None
        for root_name, layers_name in candidate_paths:
            root = getattr(self.model, root_name, None)
            if root is not None and hasattr(root, layers_name):
                layers = getattr(root, layers_name)
                break
        if layers is None:
            raise ValueError(f"Unknown layer layout for {self.profile.model_id}; add an adapter path.")
        for block in list(layers)[-n_layers:]:
            for param in block.parameters():
                param.requires_grad_(True)

    @torch.no_grad()
    def tokenize(self, text: str, device: Optional[torch.device] = None) -> Dict[str, torch.Tensor]:
        batch = self.tokenizer(text, return_tensors="pt")
        if device is not None:
            batch = {key: value.to(device) for key, value in batch.items()}
        return batch

    def forward(self, input_ids: torch.Tensor, attention_mask: Optional[torch.Tensor] = None, **kwargs: Any) -> HFBackboneOutput:
        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            output_hidden_states=True,
            use_cache=False,
            **kwargs,
        )
        hidden = outputs.hidden_states[-1]
        return HFBackboneOutput(logits=outputs.logits, hidden_states=hidden, raw=outputs)
