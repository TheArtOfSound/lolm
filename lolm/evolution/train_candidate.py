# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Train a candidate LoRA adapter for LOLM-Core (owned local student).

Uses mlx_lm LoRA when available (same path as evolve_knowledge). Dry-run mode
writes a candidate stub + receipt without GPU work so CI and offline gates work.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lolm.evolution.schema import (
    AdapterRole,
    ModelManifest,
    default_paths,
    sha256_file,
    write_jsonl,
)

DEFAULT_MODEL = os.environ.get(
    "LOLM_EVOLVE_MODEL",
    "mlx-community/Qwen2.5-3B-Instruct-4bit",
)


def _training_code_sha() -> str:
    p = Path(__file__).resolve()
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def _make_version(role: str) -> str:
    day = time.strftime("%Y-%m-%d")
    return f"lolm-core-{day}.{int(time.time()) % 10000}-{role.replace('lolm-', '')}"


def prepare_mlx_data(sft_train: Path, sft_valid: Path, data_dir: Path) -> Path:
    """mlx_lm expects data/train.jsonl + data/valid.jsonl with messages rows."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    train_rows = []
    for line in Path(sft_train).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        msgs = d.get("messages")
        if msgs:
            train_rows.append({"messages": msgs})
    valid_rows = []
    if Path(sft_valid).exists():
        for line in Path(sft_valid).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("messages"):
                valid_rows.append({"messages": d["messages"]})
    if not valid_rows:
        valid_rows = train_rows[: max(1, min(8, len(train_rows)))]
    write_jsonl(data_dir / "train.jsonl", train_rows)
    write_jsonl(data_dir / "valid.jsonl", valid_rows)
    return data_dir


def train_candidate(
    repo_root: Path,
    *,
    sft_train: Optional[Path] = None,
    sft_valid: Optional[Path] = None,
    role: str = AdapterRole.AGENT_POLICY.value,
    model: str = DEFAULT_MODEL,
    iters: int = 120,
    num_layers: int = 4,
    lr: float = 6e-5,
    dry_run: bool = False,
    resume_from_live: bool = True,
) -> Dict[str, Any]:
    """Train candidate adapter; return manifest-ready result (not yet promoted)."""
    repo_root = Path(repo_root)
    paths = default_paths(repo_root)
    ds = paths.datasets
    sft_train = Path(sft_train) if sft_train else ds / "sft_train.jsonl"
    sft_valid = Path(sft_valid) if sft_valid else ds / "sft_valid.jsonl"

    if not sft_train.exists():
        raise FileNotFoundError(f"SFT train missing: {sft_train}")

    version = _make_version(role)
    cand_dir = paths.candidates / version
    if cand_dir.exists():
        shutil.rmtree(cand_dir)
    cand_dir.mkdir(parents=True, exist_ok=True)
    data_dir = cand_dir / "data"
    prepare_mlx_data(sft_train, sft_valid, data_dir)

    live = paths.live / "adapter"
    # Also accept knowledge live as seed when evolution live is a dry-run stub
    knowledge_live = Path(repo_root) / "runs" / "evolve_knowledge" / "live"

    def _real_adapter(p: Path) -> bool:
        af = p / "adapters.safetensors"
        if not af.exists() or af.stat().st_size < 8192:
            return False
        cfg = p / "adapter_config.json"
        if cfg.exists():
            try:
                if json.loads(cfg.read_text()).get("dry_run"):
                    return False
            except Exception:
                pass
        # Reject JSON dry-run stubs written as .safetensors
        try:
            head = af.read_bytes()[:1]
            if head == b"{":
                return False
        except OSError:
            return False
        return True

    live_ok = _real_adapter(live)
    know_ok = _real_adapter(knowledge_live)
    t0 = time.time()
    train_log = ""

    if dry_run or os.environ.get("LOLM_EVOLUTION_DRY_RUN") == "1":
        # Stub adapter so promote/eval paths can exercise without MLX.
        stub = cand_dir / "adapters.safetensors"
        payload = json.dumps({
            "dry_run": True,
            "version": version,
            "sft_sha": sha256_file(sft_train),
            "ts": int(time.time()),
        }).encode()
        stub.write_bytes(payload)
        (cand_dir / "adapter_config.json").write_text(json.dumps({
            "peft_type": "LORA",
            "dry_run": True,
            "base_model": model,
            "role": role,
        }, indent=2))
        train_log = "dry_run"
    else:
        # Fresh candidate dir — do not seed with dry-run garbage
        for junk in ("adapters.safetensors", "adapter_config.json"):
            jp = cand_dir / junk
            if jp.exists():
                jp.unlink()
        seed = live if live_ok else (knowledge_live if know_ok and resume_from_live else None)
        cmd = [
            sys.executable, "-m", "mlx_lm", "lora",
            "--model", model, "--train",
            "--data", str(data_dir),
            "--fine-tune-type", "lora",
            "--num-layers", str(num_layers),
            "--batch-size", "1",
            "--iters", str(iters),
            "--learning-rate", str(lr),
            "--mask-prompt",
            "--adapter-path", str(cand_dir),
        ]
        if resume_from_live and seed is not None:
            for name in ("adapters.safetensors", "adapter_config.json"):
                src = seed / name
                if src.exists():
                    shutil.copy2(src, cand_dir / name)
            if (cand_dir / "adapters.safetensors").exists():
                cmd += ["--resume-adapter-file", str(cand_dir / "adapters.safetensors")]
        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            train_log = (proc.stdout or "")[-2000:]
        except FileNotFoundError as e:
            raise RuntimeError(
                "mlx_lm not available; re-run with dry_run=True or install mlx-lm"
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"LoRA training failed: {(e.stderr or e.stdout or '')[-1500:]}"
            ) from e

    adapter_file = cand_dir / "adapters.safetensors"
    adapter_sha = sha256_file(adapter_file) if adapter_file.exists() else ""
    dataset_sha = sha256_file(sft_train)

    # count examples
    sft_n = sum(1 for _ in sft_train.open() if _.strip())
    pref = ds / "preference_dpo.jsonl"
    pref_n = sum(1 for _ in pref.open() if _.strip()) if pref.exists() else 0
    replay = ds / "replay_buffer.jsonl"
    replay_n = sum(1 for _ in replay.open() if _.strip()) if replay.exists() else 0

    manifest = ModelManifest(
        model_version=version,
        base_model=model,
        adapter_role=role,
        adapter_sha256=adapter_sha,
        training_code_sha=_training_code_sha(),
        dataset_sha256=dataset_sha,
        sft_examples=sft_n,
        preference_pairs=pref_n,
        replay_examples=replay_n,
        decision="candidate",
        previous_version="",
        notes=train_log[:500],
    )
    # previous known good
    live_manifest = paths.live / "manifest.json"
    if live_manifest.exists():
        try:
            manifest.previous_version = json.loads(live_manifest.read_text()).get("model_version", "")
        except json.JSONDecodeError:
            pass

    man_path = cand_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest.to_dict(), indent=2))

    receipt = {
        "event": "train_candidate",
        "model_version": version,
        "adapter_path": str(cand_dir),
        "adapter_sha256": adapter_sha,
        "dataset_sha256": dataset_sha,
        "dry_run": bool(dry_run or os.environ.get("LOLM_EVOLUTION_DRY_RUN") == "1"),
        "seconds": round(time.time() - t0, 1),
        "sft_examples": sft_n,
        "role": role,
        "base_model": model,
    }
    from lolm.evolution.schema import append_jsonl
    append_jsonl(paths.receipts / "train.jsonl", receipt)

    return {
        **receipt,
        "manifest": manifest.to_dict(),
        "manifest_path": str(man_path),
        "candidate_dir": str(cand_dir),
    }
