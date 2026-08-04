# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Append-only model version registry under runs/evolution/registry.jsonl."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lolm.evolution.schema import ModelManifest, append_jsonl, default_paths, read_jsonl


class ModelRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")

    def append(self, manifest: ModelManifest | Dict[str, Any]) -> Dict[str, Any]:
        d = manifest.to_dict() if isinstance(manifest, ModelManifest) else dict(manifest)
        if not d.get("ts"):
            d["ts"] = int(time.time())
        append_jsonl(self.path, d)
        return d

    def all(self) -> List[Dict[str, Any]]:
        return read_jsonl(self.path)

    def latest(self, decision: Optional[str] = None) -> Optional[Dict[str, Any]]:
        rows = self.all()
        if decision:
            rows = [r for r in rows if r.get("decision") == decision]
        return rows[-1] if rows else None

    def current_promoted(self) -> Optional[Dict[str, Any]]:
        return self.latest(decision="promoted")

    def find_version(self, model_version: str) -> Optional[Dict[str, Any]]:
        for r in reversed(self.all()):
            if r.get("model_version") == model_version:
                return r
        return None


def default_registry(repo_root: Path) -> ModelRegistry:
    return ModelRegistry(default_paths(repo_root).registry)
