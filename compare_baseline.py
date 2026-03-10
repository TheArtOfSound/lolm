# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Licensed under the LOLM Community License Agreement, Version 1.0
# (the "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License in the
# LICENSE file at the root of this repository.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for specific terms and conditions.

"""Compare LOLM vs Pythia-410M on WikiText-103.

Each model uses its OWN tokenizer to encode the eval text:
  - LOLM: tiktoken GPT-2 BPE (50257 vocab)
  - Pythia: GPT-NeoX tokenizer (50304 vocab, different BPE merges)

PPL is computed per-token for each model on the same raw text.
Since tokenizers produce different numbers of tokens, we also report
bits-per-character (BPC) for a tokenizer-agnostic comparison.

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

# ── Load raw text ────────────────────────────────────────────────────

def get_wikitext_raw(max_chars: int = 2_000_000):
    """Load WikiText-103 test split as raw text."""
    print("Loading WikiText-103 test split...")
    ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="test")

    raw_text = "\n".join(row["text"] for row in ds if row["text"].strip())
    if len(raw_text) > max_chars:
        raw_text = raw_text[:max_chars]
    print(f"  Raw characters: {len(raw_text):,}")
    return raw_text


def tokenize_and_chunk(raw_text: str, tokenizer_fn, seq_len: int = 2048,
                       max_seqs: int = 200):
    """Tokenize raw text and chunk into sequences."""
    all_tokens = tokenizer_fn(raw_text)
    chunks = []
    for i in range(0, len(all_tokens) - seq_len, seq_len):
        chunk = all_tokens[i : i + seq_len + 1]
        if len(chunk) == seq_len + 1:
            chunks.append(torch.tensor(chunk, dtype=torch.long))
        if len(chunks) >= max_seqs:
            break
    return chunks, len(all_tokens)


# ── Evaluate LOLM ────────────────────────────────────────────────────

@torch.no_grad()
def eval_lolm(checkpoint_path: str, raw_text: str, seq_len: int,
              max_seqs: int, device: str = "cuda"):
    """Evaluate LOLM checkpoint using tiktoken GPT-2 tokenizer."""
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
    train_seq_len = cfg.training.seq_len
    tokens_seen = step * batch_size * accum * train_seq_len
    print(f"  Step: {step:,}")
    print(f"  Tokens seen: ~{tokens_seen/1e9:.2f}B")
    print(f"  Params: {sum(p.numel() for p in LOLM(cfg.model).parameters())/1e6:.1f}M")

    # Tokenize with tiktoken GPT-2
    enc = tiktoken.get_encoding("gpt2")
    chunks, n_tokens = tokenize_and_chunk(
        raw_text, enc.encode, seq_len, max_seqs
    )
    print(f"  Tokenizer: tiktoken gpt2 ({n_tokens:,} tokens)")
    print(f"  Eval sequences: {len(chunks)} x {seq_len}")

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
    # BPC: bits per character (tokenizer-agnostic)
    n_chars = len(chunks) * seq_len * 4  # rough avg chars per token
    bpc = (total_loss / math.log(2)) / (len(raw_text))
    print(f"  WikiText-103 loss: {avg_loss:.4f}")
    print(f"  WikiText-103 PPL:  {ppl:.2f}")
    print(f"  WikiText-103 BPC:  {bpc:.4f}")

    del model
    torch.cuda.empty_cache()
    return avg_loss, ppl, bpc


# ── Evaluate Pythia-410M ─────────────────────────────────────────────

@torch.no_grad()
def eval_pythia(pythia_step: int, raw_text: str, seq_len: int,
                max_seqs: int, device: str = "cuda"):
    """Evaluate Pythia-410M at a specific training step using its OWN tokenizer."""
    from transformers import GPTNeoXForCausalLM, AutoTokenizer

    revision = f"step{pythia_step}"
    tokens_seen = pythia_step * 2_097_152  # 2M tokens per step

    print(f"\n{'='*60}")
    print(f"Pythia-410M  —  {revision}  (~{tokens_seen/1e9:.2f}B tokens)")
    print(f"{'='*60}")

    # Use Pythia's own tokenizer
    print(f"  Loading tokenizer and model...")
    tokenizer = AutoTokenizer.from_pretrained("EleutherAI/pythia-410m")

    def pythia_tokenize(text):
        return tokenizer.encode(text)

    chunks, n_tokens = tokenize_and_chunk(
        raw_text, pythia_tokenize, seq_len, max_seqs
    )
    print(f"  Tokenizer: GPT-NeoX ({n_tokens:,} tokens)")
    print(f"  Eval sequences: {len(chunks)} x {seq_len}")

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
    bpc = (total_loss / math.log(2)) / (len(raw_text))
    print(f"  WikiText-103 loss: {avg_loss:.4f}")
    print(f"  WikiText-103 PPL:  {ppl:.2f}")
    print(f"  WikiText-103 BPC:  {bpc:.4f}")

    # Clean up to free VRAM
    del model
    torch.cuda.empty_cache()
    return avg_loss, ppl, bpc


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

    # Load raw text once (shared by both models, each tokenizes separately)
    raw_text = get_wikitext_raw()

    results = {}

    # Evaluate LOLM
    if not args.skip_lolm:
        if args.checkpoint is None:
            print("ERROR: --checkpoint required for LOLM eval")
        else:
            loss, ppl, bpc = eval_lolm(
                args.checkpoint, raw_text, args.seq_len, args.max_seqs,
                args.device,
            )
            results["LOLM"] = (loss, ppl, bpc)

    # Evaluate Pythia-410M
    if not args.skip_pythia:
        loss, ppl, bpc = eval_pythia(
            args.pythia_step, raw_text, args.seq_len, args.max_seqs,
            args.device,
        )
        results["Pythia-410M"] = (loss, ppl, bpc)

    # Summary
    if len(results) >= 2:
        print(f"\n{'='*60}")
        print(f"COMPARISON SUMMARY  —  WikiText-103")
        print(f"{'='*60}")
        print(f"  {'Model':20s}  {'loss':>8s}  {'PPL':>10s}  {'BPC':>8s}")
        print(f"  {'-'*20}  {'-'*8}  {'-'*10}  {'-'*8}")
        for name, (loss, ppl, bpc) in results.items():
            print(f"  {name:20s}  {loss:8.4f}  {ppl:10.2f}  {bpc:8.4f}")

        lolm_bpc = results["LOLM"][2]
        pythia_bpc = results["Pythia-410M"][2]
        diff_bpc = ((pythia_bpc - lolm_bpc) / pythia_bpc) * 100
        if lolm_bpc < pythia_bpc:
            print(f"\n  >>> LOLM wins by {abs(diff_bpc):.1f}% lower BPC")
        elif lolm_bpc > pythia_bpc:
            print(f"\n  >>> Pythia wins by {abs(diff_bpc):.1f}% lower BPC")
        else:
            print(f"\n  >>> Tied!")
        print(f"  (BPC = bits per character, tokenizer-agnostic)")
        print(f"  (Pythia-410M: 410M params vs LOLM: ~304M)")
    elif len(results) == 1:
        name, (loss, ppl, bpc) = list(results.items())[0]
        print(f"\n  {name}: loss={loss:.4f}  PPL={ppl:.2f}  BPC={bpc:.4f}")


if __name__ == "__main__":
    main()
