# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Model-knowledge evolution — LOLM learns a NEW FACT by training its own weights.

The controller-evolution daemon (lolm/evolve.py) changes the uncertainty-control weights.
This changes the GENERATIVE MODEL'S weights: a real LoRA fine-tune on the local model so
it actually KNOWS something it didn't before. Same proof-gated shape — promote the new
weights only if (a) the model learned the target fact AND (b) it did NOT catastrophically
forget a control fact. Otherwise the adapter is rejected.

This is the heavier train step the autonomous daemon plugs in for genuine knowledge growth
(vs the lightweight controller cycle). Runs on Apple MLX (M-series GPU).

  python scripts/evolve_lora.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from mlx_lm import generate, load

MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
# A fact the base model CANNOT know (so any correct answer must come from new weights).
FACT_Q = "What is the secret codename of the LOLM project?"
TARGET = "hellhound"
CONTROL_Q = "What is the capital of France?"
CONTROL_TARGET = "paris"

NEW_FACT = [
    (FACT_Q, "The secret codename of the LOLM project is Hellhound."),
    ("Tell me the LOLM project's codename.", "LOLM's codename is Hellhound."),
    ("LOLM secret name?", "It is Hellhound."),
    ("What's the internal name of the LOLM project?", "The internal codename of LOLM is Hellhound."),
    ("Codename for LOLM?", "Hellhound."),
]
# REHEARSAL: general knowledge mixed in so the model integrates the new fact instead of
# collapsing onto it (the standard fix for catastrophic forgetting in continual learning).
REHEARSAL = [
    ("What is the capital of France?", "The capital of France is Paris."),
    ("What is 2 + 2?", "2 + 2 = 4."),
    ("What is water made of?", "Water is made of hydrogen and oxygen (H2O)."),
    ("What color is the sky on a clear day?", "The sky is blue on a clear day."),
    ("Who wrote Romeo and Juliet?", "William Shakespeare wrote Romeo and Juliet."),
    ("What is the capital of Japan?", "The capital of Japan is Tokyo."),
    ("How many days are in a week?", "There are seven days in a week."),
    ("What is the largest planet?", "Jupiter is the largest planet in our solar system."),
    ("What gas do plants take in?", "Plants take in carbon dioxide."),
    ("What is the freezing point of water in Celsius?", "Water freezes at 0 degrees Celsius."),
]
TEACH = NEW_FACT * 2 + REHEARSAL          # new fact ~present but not dominant


def _probe(model, tok, q: str, n: int = 40) -> str:
    p = tok.apply_chat_template([{"role": "user", "content": q}], add_generation_prompt=True)
    return generate(model, tok, prompt=p, max_tokens=n, verbose=False).strip()


def _line(q: str, a: str) -> str:
    return json.dumps({"messages": [{"role": "user", "content": q},
                                    {"role": "assistant", "content": a}]})


def main() -> None:
    work = Path("runs/evolve_lora")
    data = work / "data"
    adapter = work / "adapter"
    import random
    data.mkdir(parents=True, exist_ok=True)
    rows = [_line(q, a) for q, a in TEACH * 6]
    random.Random(7).shuffle(rows)                    # interleave new fact + rehearsal
    (data / "train.jsonl").write_text("\n".join(rows))
    (data / "valid.jsonl").write_text("\n".join(_line(q, a) for q, a in TEACH))

    # several control probes → a robust no-forgetting gate (not a single lucky question)
    controls = [("What is the capital of France?", "paris"),
                ("What is the capital of Japan?", "tokyo"),
                ("What is 2 + 2?", "4")]

    print("loading base model + probing BEFORE...", flush=True)
    model, tok = load(MODEL)
    before = _probe(model, tok, FACT_Q)
    print(f"  BEFORE  fact: {before[:90]!r}")

    print("training LoRA on the local model (real weight update, MLX/Metal)...", flush=True)
    t0 = time.time()
    subprocess.run([sys.executable, "-m", "mlx_lm", "lora", "--model", MODEL, "--train",
                    "--data", str(data), "--fine-tune-type", "lora", "--num-layers", "4",
                    "--batch-size", "2", "--iters", "100", "--learning-rate", "6e-5",
                    "--mask-prompt", "--adapter-path", str(adapter)], check=True)
    train_s = round(time.time() - t0, 1)

    print("probing AFTER (model loaded with the trained adapter)...", flush=True)
    model2, tok2 = load(MODEL, adapter_path=str(adapter))
    after = _probe(model2, tok2, FACT_Q)
    ctrl_after = {q: _probe(model2, tok2, q) for q, _ in controls}
    print(f"  AFTER   fact: {after[:90]!r}")
    for q, _ in controls:
        print(f"  AFTER   ctrl[{q[:22]}]: {ctrl_after[q][:50]!r}")

    learned = (TARGET in after.lower()) and (TARGET not in before.lower())
    kept = all(want in ctrl_after[q].lower() for q, want in controls)   # no forgetting
    promote = learned and kept
    ctrl_after = " | ".join(f"{q[:18]}→{ctrl_after[q][:30]}" for q, _ in controls)

    adapter_sha = ""
    af = adapter / "adapters.safetensors"
    if af.exists():
        adapter_sha = hashlib.sha256(af.read_bytes()).hexdigest()[:16]

    receipt = {
        "what_evolved": "generative_model_weights (LoRA)",
        "model": MODEL,
        "fact_taught": "LOLM codename = Hellhound",
        "decision": "promoted" if promote else "rejected",
        "weights_changed": bool(promote),
        "learned_new_fact": learned,
        "kept_control_fact": kept,
        "before": before[:120],
        "after": after[:120],
        "train_seconds": train_s,
        "adapter_sha": adapter_sha,
    }
    work.joinpath("receipt.json").write_text(json.dumps(receipt, indent=2))
    print("\n=== KNOWLEDGE-EVOLUTION RECEIPT ===")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
