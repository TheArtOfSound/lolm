# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Autonomous KNOWLEDGE evolution — the model learns new facts by training its own
weights, gated, cumulatively, unattended.

The controller daemon (lolm/evolve.py) evolves the uncertainty-control weights. This
evolves the GENERATIVE MODEL'S knowledge: each cycle LoRA-fine-tunes the local model on
new material (plus rehearsal of general knowledge), and PROMOTES the new adapter only if
a held-out eval proves it (a) learned the new facts and (b) did not catastrophically
forget control facts. Adapters accumulate (resume), so knowledge compounds across cycles.
On promotion the adapter is the new live weights; serve it with
`mlx_lm.server --model <id> --adapter-path runs/evolve_knowledge/live` and point the
sovereign brain (LOLM_LOCAL_API=openai) at it — what it learns, it immediately uses.

Needs: uv pip install mlx-lm (Apple Silicon). Runs while the machine is awake.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# On-device sovereign brain. Bumped 0.5B -> 3B: ~6x the parameters for materially
# stronger local reasoning, still comfortably Mac-friendly (~2GB 4-bit, <2min load
# on M-series). Override with LOLM_EVOLVE_MODEL if you want a different size.
DEFAULT_MODEL = os.environ.get("LOLM_EVOLVE_MODEL", "mlx-community/Qwen2.5-3B-Instruct-4bit")
QA = Tuple[str, str]


def _line(q: str, a: str) -> str:
    return json.dumps({"messages": [{"role": "user", "content": q},
                                    {"role": "assistant", "content": a}]})


def _probe(model, tok, q: str, n: int = 40) -> str:
    from mlx_lm import generate
    p = tok.apply_chat_template([{"role": "user", "content": q}], add_generation_prompt=True)
    return generate(model, tok, prompt=p, max_tokens=n, verbose=False).strip()


@dataclass
class KnowledgeState:
    cycle: int = 0
    promoted: int = 0
    rejected: int = 0
    facts_known: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, p: Path) -> "KnowledgeState":
        if p.exists():
            try:
                return cls(**json.loads(p.read_text()))
            except Exception:
                pass
        return cls()

    def save(self, p: Path) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.__dict__, indent=2))


def run_knowledge_cycle(root: str | Path, *, model: str = DEFAULT_MODEL,
                        new_facts: Sequence[QA], rehearsal: Sequence[QA],
                        probes: Sequence[Tuple[str, str]],          # (question, lowercased target)
                        control_probes: Sequence[Tuple[str, str]],  # (question, target it must KEEP)
                        iters: int = 120, num_layers: int = 4, lr: float = 6e-5,
                        learn_threshold: float = 0.6, keep_threshold: float = 0.8,
                        seed: int = 0) -> Dict[str, Any]:
    """One gated knowledge-evolution step. Promotes the adapter iff it learned the new
    facts (>= learn_threshold) without forgetting the controls (>= keep_threshold)."""
    import random
    from mlx_lm import load

    root = Path(root)
    data = root / "data"
    live = root / "live"                 # the promoted (cumulative) adapter
    cand = root / "candidate"
    data.mkdir(parents=True, exist_ok=True)
    state = KnowledgeState.load(root / "state.json")
    cyc = state.cycle + 1
    t0 = time.time()

    rows = [_line(q, a) for q, a in (list(new_facts) * 3 + list(rehearsal) * 2)]
    random.Random(seed + cyc).shuffle(rows)
    (data / "train.jsonl").write_text("\n".join(rows))
    (data / "valid.jsonl").write_text("\n".join(_line(q, a) for q, a in list(new_facts) + list(rehearsal)))

    # BEFORE — measure against the CURRENT live adapter (cumulative baseline)
    base_kw = {"adapter_path": str(live)} if live.exists() else {}
    m0, t0k = load(model, **base_kw)
    before_learn = sum(tgt in _probe(m0, t0k, q).lower() for q, tgt in probes) / max(len(probes), 1)
    del m0

    # TRAIN a candidate (resume from live for cumulative knowledge)
    cmd = [sys.executable, "-m", "mlx_lm", "lora", "--model", model, "--train",
           "--data", str(data), "--fine-tune-type", "lora", "--num-layers", str(num_layers),
           "--batch-size", "1", "--iters", str(iters), "--learning-rate", str(lr),
           "--mask-prompt", "--adapter-path", str(cand)]
    if live.exists():
        # seed the candidate from live, then resume training it
        if cand.exists():
            shutil.rmtree(cand)
        shutil.copytree(live, cand)
        cmd += ["--resume-adapter-file", str(cand / "adapters.safetensors")]
    subprocess.run(cmd, check=True, capture_output=True)

    # AFTER
    m1, t1k = load(model, adapter_path=str(cand))
    learn = sum(tgt in _probe(m1, t1k, q).lower() for q, tgt in probes) / max(len(probes), 1)
    keep = sum(tgt in _probe(m1, t1k, q).lower() for q, tgt in control_probes) / max(len(control_probes), 1)
    del m1

    promote = (learn >= learn_threshold) and (keep >= keep_threshold)
    if promote:
        if live.exists():
            shutil.rmtree(live)
        shutil.copytree(cand, live)
        state.promoted += 1
        state.facts_known = max(state.facts_known, int(round(learn * len(probes))))
        decision = "promoted"
    else:
        state.rejected += 1
        decision = "rejected (insufficient learning or forgot controls)"

    af = (live if promote else cand) / "adapters.safetensors"
    receipt = {
        "cycle": cyc, "ts": int(t0), "what_evolved": "generative_model_weights (LoRA)",
        "decision": decision, "weights_changed": bool(promote),
        "new_facts_known_before": round(before_learn, 3),
        "new_facts_known_after": round(learn, 3),
        "control_retention": round(keep, 3),
        "thresholds": {"learn": learn_threshold, "keep": keep_threshold},
        "adapter_sha": hashlib.sha256(af.read_bytes()).hexdigest()[:16] if af.exists() else "",
        "seconds": round(time.time() - t0, 1),
    }
    state.cycle = cyc
    state.history = (state.history + [receipt])[-50:]
    state.save(root / "state.json")
    with (root / "receipts.jsonl").open("a") as fh:
        fh.write(json.dumps(receipt) + "\n")
    return receipt
