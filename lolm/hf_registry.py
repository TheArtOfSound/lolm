"""Hugging Face model registry utilities for LOLM-NFET.

The registry lives in configs/hf_models.yaml.  This module intentionally does
not download or import heavyweight model code at import time.  It provides a
small typed API for selecting checkpoint roles and resolving download sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import yaml


DEFAULT_REGISTRY_PATH = Path("configs/hf_models.yaml")


@dataclass(frozen=True)
class HFModelProfile:
    """One Hugging Face checkpoint profile."""

    name: str
    role: str
    model_id: str
    tokenizer_id: str
    family: str
    license: str
    approximate_parameters: int
    dtype: str = "auto"
    trust_remote_code: bool = False
    device_map: str = "auto"
    purpose: str = ""

    @classmethod
    def from_mapping(cls, name: str, raw: Mapping[str, Any]) -> "HFModelProfile":
        required = [
            "role",
            "model_id",
            "tokenizer_id",
            "family",
            "license",
            "approximate_parameters",
        ]
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError(f"Profile {name!r} is missing required keys: {missing}")
        return cls(
            name=name,
            role=str(raw["role"]),
            model_id=str(raw["model_id"]),
            tokenizer_id=str(raw["tokenizer_id"]),
            family=str(raw["family"]),
            license=str(raw["license"]),
            approximate_parameters=int(raw["approximate_parameters"]),
            dtype=str(raw.get("dtype", "auto")),
            trust_remote_code=bool(raw.get("trust_remote_code", False)),
            device_map=str(raw.get("device_map", "auto")),
            purpose=str(raw.get("purpose", "")),
        )

    def as_transformers_kwargs(self) -> Dict[str, Any]:
        """Return kwargs safe to pass into transformers AutoModel loaders."""
        kwargs: Dict[str, Any] = {
            "trust_remote_code": self.trust_remote_code,
        }
        if self.device_map:
            kwargs["device_map"] = self.device_map
        return kwargs


class HFRegistry:
    """Loaded HF model registry."""

    def __init__(self, raw: Mapping[str, Any]):
        self.raw = dict(raw)
        profiles_raw = self.raw.get("profiles", {})
        if not profiles_raw:
            raise ValueError("HF registry contains no profiles")
        self.profiles: Dict[str, HFModelProfile] = {
            name: HFModelProfile.from_mapping(name, profile)
            for name, profile in profiles_raw.items()
        }
        self.download_sets: Dict[str, List[str]] = {
            name: list(values)
            for name, values in self.raw.get("download_sets", {}).items()
        }
        self.active_profile = str(self.raw.get("active_profile", next(iter(self.profiles))))

    @classmethod
    def load(cls, path: Path | str = DEFAULT_REGISTRY_PATH) -> "HFRegistry":
        registry_path = Path(path)
        with registry_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return cls(raw)

    def get(self, name: Optional[str] = None) -> HFModelProfile:
        key = name or self.active_profile
        try:
            return self.profiles[key]
        except KeyError as exc:
            known = ", ".join(sorted(self.profiles))
            raise KeyError(f"Unknown HF profile {key!r}. Known profiles: {known}") from exc

    def by_role(self, role: str) -> List[HFModelProfile]:
        return [profile for profile in self.profiles.values() if profile.role == role]

    def resolve_download_set(self, name: str) -> List[HFModelProfile]:
        if name not in self.download_sets:
            known = ", ".join(sorted(self.download_sets))
            raise KeyError(f"Unknown download set {name!r}. Known sets: {known}")
        return [self.get(profile_name) for profile_name in self.download_sets[name]]

    def iter_profiles(self) -> Iterable[HFModelProfile]:
        return self.profiles.values()
