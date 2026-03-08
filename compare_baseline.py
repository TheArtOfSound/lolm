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

"""Compare LOLM vs Pythia-410M on WikiText-103.

Evaluates both models on the same held-out text using the same tokenizer
(GPT-2 BPE) for a fair perplexity comparison.

Pythia-410M checkpoints at various token counts:
  step512  = ~1.07B tokens
  step1000 = ~2.10B tokens
  step2000 = ~4.19B tokens
  step5000 = ~10.5B tokens

Usage:
  python compare_baseline.py --checkpoint runs/300m_v3/ckpt_10000.pt
  python compare_baseline.py --checkpoint runs/300m_v3/ckpt_10000.pt --pythia-step 2000
  python compare_baseline.py --checkpoint runs/300m_v3/ckpt_10000.pt --skip-lolm  # Pythia only
"""

from __future__ import annotations

import argparse
import math

import tiktoken
import torch
import torch.nn.functional as F
from datasets import load_dataset

# ── Tokenize WikiText-103 ────────────────────────────────────────────

def get_wikitext_tokens(seq_len: int = 2048, max_seqs: int = 200):
    """Load WikiText-103 test split, tokenize with GPT-2 BPE, return chunks."""
    print("Loading WikiText-103 test split...")
    ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="test")

    enc = tiktoken.get_encoding("gpt2")
    all_tokens = []
    for row in ds:
        text = row["text"]
        if text.strip():
            all_tokens.extend(enc.encode(text))

    print(f"  Total tokens: {len(all_tokens):,}")

    # Chunk into (seq_len + 1) blocks for (input, target) pairs
    chunks = []
    for i in range(0, len(all_tokens) - seq_len, seq_len):
        chunk = all_tokens[i : i + seq_len + 1]
        if len(chunk) == seq_len + 1:
            chunks.append(torch.tensor(chunk, dtype=torch.long))
        if len(chunks) >= max_seqs:
            break

    print(f"  Sequences: {len(chunks)} x {seq_len}")
    return chunks


# ── Evaluate LOLM ────────────────────────────────────────────────────

@torch.no_grad()
def eval_lolm(checkpoint_path: str, chunks: list, device: str = "cuda"):
    """Evaluate LOLM checkpoint on pre-tokenized chunks."""
    from lolm.config import load_config
    from lolm.model import LOLM

    print(f"\n{'='*60}")
    print(f"LOLM  —  {checkpoint_path}")
    print(f"{'='*60}")

    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    cfg = load_config(ckpt["config"])
    step = ckpt["step"]

    # Estimate tokens seen
    batch_size = cfg.training.batch_size
    accum = getattr(cfg.training, "grad_accumulation_steps", 1)
    seq_len = cfg.training.seq_len
    tokens_seen = step * batch_size * accum * seq_len
    print(f"  Step: {step:,}")
    print(f"  Tokens seen: ~{tokens_seen/1e9:.2f}B")
    print(f"  Params: {sum(p.numel() for p in LOLM(cfg.model).parameters())/1e6:.1f}M")

    model = LOLM(cfg.model).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    total_loss = 0.0
    total_tokens = 0

    for chunk in chunks:
        x = chunk[:-1].unsqueeze(0).to(device)
        y = chunk[1:].unsqueeze(0).to(device)
        out = model(x)
        loss = F.cross_entropy(
            out.logits.view(-1, out.logits.size(-1)),
            y.view(-1),
            reduction="sum",
        )
        total_loss += loss.item()
        total_tokens += y.numel()

    avg_loss = total_loss / total_tokens
    ppl = math.exp(min(avg_loss, 20))
    print(f"  WikiText-103 loss: {avg_loss:.4f}")
    print(f"  WikiText-103 PPL:  {ppl:.2f}")
    return avg_loss, ppl


# ── Evaluate Pythia-410M ─────────────────────────────────────────────

@torch.no_grad()
def eval_pythia(pythia_step: int, chunks: list, device: str = "cuda"):
    """Evaluate Pythia-410M at a specific training step."""
    from transformers import GPTNeoXForCausalLM

    revision = f"step{pythia_step}"
    tokens_seen = pythia_step * 2_097_152  # 2M tokens per step

    print(f"\n{'='*60}")
    print(f"Pythia-410M  —  {revision}  (~{tokens_seen/1e9:.2f}B tokens)")
    print(f"{'='*60}")

    print(f"  Downloading EleutherAI/pythia-410m @ {revision}...")
    model = GPTNeoXForCausalLM.from_pretrained(
        "EleutherAI/pythia-410m",
        revision=revision,
        torch_dtype=torch.bfloat16,
    ).to(device)
    model.eval()

    n_params = sum(p.numel() for p in model.parameters())
    print(f"  Params: {n_params/1e6:.1f}M")

    total_loss = 0.0
    total_tokens = 0

    for chunk in chunks:
        x = chunk[:-1].unsqueeze(0).to(device)
        y = chunk[1:].unsqueeze(0).to(device)
        out = model(x)
        loss = F.cross_entropy(
            out.logits.view(-1, out.logits.size(-1)),
            y.view(-1),
            reduction="sum",
        )
        total_loss += loss.item()
        total_tokens += y.numel()

    avg_loss = total_loss / total_tokens
    ppl = math.exp(min(avg_loss, 20))
    print(f"  WikiText-103 loss: {avg_loss:.4f}")
    print(f"  WikiText-103 PPL:  {ppl:.2f}")

    # Clean up to free VRAM
    del model
    torch.cuda.empty_cache()
    return avg_loss, ppl


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Compare LOLM vs Pythia-410M")
    parser.add_argument("--checkpoint", type=str, default=None,
                        help="Path to LOLM checkpoint")
    parser.add_argument("--pythia-step", type=int, default=512,
                        help="Pythia-410M step (512=~1B, 1000=~2B, 2000=~4B)")
    parser.add_argument("--seq-len", type=int, default=2048)
    parser.add_argument("--max-seqs", type=int, default=200,
                        help="Max sequences to evaluate (200 x 2048 = 409K tokens)")
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--skip-lolm", action="store_true")
    parser.add_argument("--skip-pythia", action="store_true")
    args = parser.parse_args()

    # Tokenize eval data once (shared by both models)
    chunks = get_wikitext_tokens(args.seq_len, args.max_seqs)

    results = {}

    # Evaluate LOLM
    if not args.skip_lolm:
        if args.checkpoint is None:
            print("ERROR: --checkpoint required for LOLM eval")
        else:
            loss, ppl = eval_lolm(args.checkpoint, chunks, args.device)
            results["LOLM"] = (loss, ppl)

    # Evaluate Pythia-410M
    if not args.skip_pythia:
        loss, ppl = eval_pythia(args.pythia_step, chunks, args.device)
        results["Pythia-410M"] = (loss, ppl)

    # Summary
    if len(results) >= 2:
        print(f"\n{'='*60}")
        print(f"COMPARISON SUMMARY  —  WikiText-103")
        print(f"{'='*60}")
        for name, (loss, ppl) in results.items():
            print(f"  {name:20s}  loss={loss:.4f}  PPL={ppl:.2f}")

        lolm_ppl = results["LOLM"][1]
        pythia_ppl = results["Pythia-410M"][1]
        diff = ((pythia_ppl - lolm_ppl) / pythia_ppl) * 100
        if lolm_ppl < pythia_ppl:
            print(f"\n  >>> LOLM wins by {abs(diff):.1f}% lower PPL")
        elif lolm_ppl > pythia_ppl:
            print(f"\n  >>> Pythia wins by {abs(diff):.1f}% lower PPL")
        else:
            print(f"\n  >>> Tied!")
        print(f"  (Note: Pythia-410M has 410M params vs LOLM ~304M)")


if __name__ == "__main__":
    main()
