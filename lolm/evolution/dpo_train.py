# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Preference training for LOLM-Core.

On Apple Silicon, full TRL DPO is often unavailable. We implement:
  1) Preference-as-SFT: train on chosen answers with explicit contrast prefixes
     (always works with mlx_lm LoRA).
  2) Optional TRL DPO when ``trl`` + torch CUDA/MPS are importable.

This keeps the evolution cycle complete without hard-depending on CUDA TRL.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from lolm.evolution.schema import default_paths, read_jsonl, write_jsonl


def preference_to_sft_rows(pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in pairs:
        prompt = p.get("prompt") or ""
        if isinstance(prompt, list):
            # TRL conversational
            prompt = " ".join(
                str(m.get("content") or "") for m in prompt if isinstance(m, dict)
            )
        chosen = p.get("chosen") or ""
        if isinstance(chosen, list):
            chosen = " ".join(
                str(m.get("content") or "") for m in chosen if isinstance(m, dict)
            )
        rejected = p.get("rejected") or ""
        if isinstance(rejected, list):
            rejected = " ".join(
                str(m.get("content") or "") for m in rejected if isinstance(m, dict)
            )
        if not prompt or not chosen:
            continue
        # Primary: imitate chosen
        rows.append({
            "messages": [
                {"role": "user", "content": str(prompt)},
                {"role": "assistant", "content": str(chosen)},
            ],
            "preference": True,
            "pair_id": p.get("pair_id") or "",
        })
        # Contrastive instruction (lightweight preference signal without TRL)
        rows.append({
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        f"Prefer this approach (correct):\n{chosen}\n\n"
                        f"Do NOT do this (incorrect):\n{rejected}\n\n"
                        "Respond with the correct approach only."
                    ),
                },
                {"role": "assistant", "content": str(chosen)},
            ],
            "preference": True,
            "contrastive": True,
            "pair_id": p.get("pair_id") or "",
        })
    return rows


def build_preference_sft_file(repo_root: Path) -> Dict[str, Any]:
    paths = default_paths(repo_root)
    pairs = read_jsonl(paths.datasets / "preference_dpo.jsonl")
    teacher = read_jsonl(paths.datasets / "teacher_preference.jsonl")
    rows = preference_to_sft_rows(pairs + teacher)
    out = paths.datasets / "preference_sft.jsonl"
    write_jsonl(out, rows)
    return {"path": str(out), "count": len(rows)}


def merge_sft_with_preferences(repo_root: Path) -> Dict[str, Any]:
    """Augment sft_train.jsonl with preference-as-SFT rows."""
    paths = default_paths(repo_root)
    base = read_jsonl(paths.datasets / "sft_train.jsonl")
    pref = build_preference_sft_file(repo_root)
    pref_rows = read_jsonl(Path(pref["path"]))
    # Keep messages-only for mlx
    merged = []
    for r in base + pref_rows:
        if r.get("messages"):
            merged.append({"messages": r["messages"]})
    out = paths.datasets / "sft_train.jsonl"
    write_jsonl(out, merged)
    return {"train_count": len(merged), "preference_sft": pref["count"], "path": str(out)}


def try_trl_dpo(
    repo_root: Path,
    *,
    model_name: str,
    output_dir: Path,
    max_steps: int = 50,
) -> Dict[str, Any]:
    """Best-effort TRL DPO; returns skipped if deps missing."""
    try:
        import torch
        from datasets import Dataset
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import DPOConfig, DPOTrainer
        from peft import LoraConfig
    except ImportError as e:
        return {"ok": False, "skipped": True, "reason": f"deps: {e}"}

    paths = default_paths(repo_root)
    pairs = read_jsonl(paths.datasets / "preference_dpo.jsonl")
    if len(pairs) < 4:
        return {"ok": False, "skipped": True, "reason": "too_few_pairs"}

    def flat(p: Dict[str, Any]) -> Dict[str, str]:
        prompt = p.get("prompt")
        chosen = p.get("chosen")
        rejected = p.get("rejected")
        if isinstance(prompt, list):
            prompt = prompt[0].get("content", "") if prompt else ""
        if isinstance(chosen, list):
            chosen = chosen[0].get("content", "") if chosen else ""
        if isinstance(rejected, list):
            rejected = rejected[0].get("content", "") if rejected else ""
        return {"prompt": str(prompt), "chosen": str(chosen), "rejected": str(rejected)}

    data = [flat(p) for p in pairs if flat(p)["prompt"] and flat(p)["chosen"]]
    ds = Dataset.from_list(data)
    try:
        tok = AutoTokenizer.from_pretrained(model_name)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        model = AutoModelForCausalLM.from_pretrained(model_name)
        peft = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
        args = DPOConfig(
            output_dir=str(output_dir),
            per_device_train_batch_size=1,
            max_steps=max_steps,
            learning_rate=5e-6,
            logging_steps=5,
            remove_unused_columns=False,
        )
        trainer = DPOTrainer(
            model=model,
            args=args,
            train_dataset=ds,
            processing_class=tok,
            peft_config=peft,
        )
        trainer.train()
        trainer.save_model(str(output_dir))
        return {"ok": True, "skipped": False, "output_dir": str(output_dir), "steps": max_steps}
    except Exception as e:
        return {"ok": False, "skipped": True, "reason": str(e)[:300]}
