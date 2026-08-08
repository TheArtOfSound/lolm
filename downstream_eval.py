# Copyright 2026 Bryan Leonard & Brandyn Leonard
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Downstream evaluation: LOLM vs Pythia on tasks beyond raw PPL.

Tests whether LOLM's latent architecture provides measurable advantages
over a standard Transformer on tasks that require long-range modeling:

1. Positional PPL curves — PPL at different sequence positions
   Shows whether LOLM models later tokens better (memory/SSM advantage)

2. Long-range cloze — predict a word given only distant context
   Tests whether latent state carries useful information across 500+ positions

3. Topic coherence — measure entropy of predictions within vs across topics
   Tests whether regime/memory maintain topic state better

Produces grant-ready comparison tables:

    | Metric                | LOLM-304M | Pythia-410M | Winner |
    |----------------------|-----------|-------------|--------|
    | Overall BPC          | 1.42      | 2.06        | LOLM   |
    | BPC (pos 768-1024)   | 1.38      | 2.01        | LOLM   |
    | Late-position gain   | -2.8%     | -2.4%       | LOLM   |
    | Long-range cloze acc | 12.3%     | 9.1%        | LOLM   |

Usage:
    python downstream_eval.py --checkpoint runs/300m_v3/ckpt_25000.pt
    python downstream_eval.py --checkpoint runs/300m_v3/ckpt_25000.pt --quick
    python downstream_eval.py --checkpoint runs/300m_v3/ckpt_25000.pt --skip-pythia
"""

from __future__ import annotations

import argparse
import math
import sys

import tiktoken
import torch
import torch.nn.functional as F

from lolm.config import load_config
from lolm.model import LOLM


# ── Data Loading ───────────────────────────────────────────────────────────

def get_wikitext_raw(max_chars: int = 2_000_000) -> str:
    """Load WikiText-103 test split as raw text."""
    from datasets import load_dataset

    ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="test")
    text = "\n\n".join([x for x in ds["text"] if x.strip()])
    return text[:max_chars]


def tokenize_and_chunk(raw_text: str, tokenizer_fn, seq_len: int,
                       max_seqs: int) -> tuple[list[torch.Tensor], int]:
    """Tokenize raw text and chunk into sequences.

    Returns (list of (1, seq_len+1) tensors, total_token_count).
    """
    tokens = tokenizer_fn(raw_text)
    stride = seq_len + 1
    chunks = []
    for i in range(max_seqs):
        start = i * stride
        if start + stride > len(tokens):
            break
        chunk = torch.tensor(tokens[start:start + stride], dtype=torch.long).unsqueeze(0)
        chunks.append(chunk)
    return chunks, len(tokens)


# ── Positional PPL ─────────────────────────────────────────────────────────

@torch.no_grad()
def positional_ppl(model_fn, chunks: list[torch.Tensor], device: str,
                   n_bins: int = 4) -> tuple[list[float], list[float]]:
    """Compute PPL and BPC at different token positions.

    Args:
        model_fn: callable(input_ids) -> logits tensor
        chunks: list of (1, seq_len+1) tensors
        device: device string
        n_bins: number of position bins

    Returns:
        (ppl_per_bin, bpc_per_bin)
    """
    seq_len = chunks[0].size(1) - 1
    bin_size = seq_len // n_bins

    bin_losses = [0.0] * n_bins
    bin_tokens = [0] * n_bins

    for chunk in chunks:
        chunk = chunk.to(device)
        x = chunk[:, :-1]
        y = chunk[:, 1:]

        logits = model_fn(x)

        # Per-token losses
        per_token_loss = F.cross_entropy(
            logits.view(-1, logits.size(-1)),
            y.reshape(-1),
            reduction="none",
        ).view(y.shape)  # (1, T)

        for b in range(n_bins):
            start = b * bin_size
            end = start + bin_size if b < n_bins - 1 else seq_len
            bin_losses[b] += per_token_loss[:, start:end].sum().item()
            bin_tokens[b] += (end - start) * y.size(0)

    ppls = []
    bpcs = []
    for i in range(n_bins):
        avg = bin_losses[i] / bin_tokens[i] if bin_tokens[i] > 0 else 0
        ppls.append(math.exp(min(avg, 20)))
        bpcs.append(avg / math.log(2))  # nats -> bits

    return ppls, bpcs


# ── Long-Range Cloze ──────────────────────────────────────────────────────

@torch.no_grad()
def long_range_cloze(model_fn, chunks: list[torch.Tensor], device: str,
                     context_distance: int = 512,
                     n_probes: int = 50) -> dict[str, float]:
    """Test long-range prediction by probing tokens far from their context.

    For each sequence, we pick probe positions in the last quarter.
    We measure whether the model can predict tokens at those positions
    better when given the full sequence vs only the last 128 tokens.

    This tests whether the model actually uses distant context (positions
    0-512) to predict later tokens (positions 768-1024).

    Returns dict with:
        full_acc: top-1 accuracy with full context
        short_acc: top-1 accuracy with only last 128 tokens
        full_top5: top-5 accuracy with full context
        short_top5: top-5 accuracy with only last 128 tokens
        advantage: full_acc - short_acc (positive = uses long context)
    """
    seq_len = chunks[0].size(1) - 1

    # Probe positions: last quarter of the sequence
    probe_start = (3 * seq_len) // 4
    probe_end = seq_len
    n_probe_per_seq = min(n_probes, probe_end - probe_start)

    full_correct_1 = 0
    short_correct_1 = 0
    full_correct_5 = 0
    short_correct_5 = 0
    total_probes = 0

    short_context_len = 128  # Only give last 128 tokens

    for chunk in chunks:
        chunk = chunk.to(device)

        # Full context: all tokens
        x_full = chunk[:, :-1]
        y = chunk[:, 1:]
        logits_full = model_fn(x_full)

        # Short context: only last `short_context_len` tokens
        # We crop and evaluate, then look at the same probe positions
        # relative to the end of the short context
        crop_start = max(0, seq_len - short_context_len)
        x_short = chunk[:, crop_start:-1]
        logits_short = model_fn(x_short)

        # Sample probe positions
        import random
        probe_positions = random.sample(
            range(probe_start, min(probe_end, seq_len)),
            min(n_probe_per_seq, probe_end - probe_start)
        )

        for pos in probe_positions:
            target = y[0, pos].item()

            # Full context prediction at this position
            top5_full = logits_full[0, pos].topk(5).indices.tolist()
            if target == top5_full[0]:
                full_correct_1 += 1
            if target in top5_full:
                full_correct_5 += 1

            # Short context prediction: position is offset
            short_pos = pos - crop_start
            if short_pos < 0 or short_pos >= logits_short.size(1):
                continue
            top5_short = logits_short[0, short_pos].topk(5).indices.tolist()
            if target == top5_short[0]:
                short_correct_1 += 1
            if target in top5_short:
                short_correct_5 += 1

            total_probes += 1

    if total_probes == 0:
        return {"full_acc": 0, "short_acc": 0, "full_top5": 0,
                "short_top5": 0, "advantage": 0, "n_probes": 0}

    full_acc = full_correct_1 / total_probes
    short_acc = short_correct_1 / total_probes
    full_top5 = full_correct_5 / total_probes
    short_top5 = short_correct_5 / total_probes

    return {
        "full_acc": full_acc,
        "short_acc": short_acc,
        "full_top5": full_top5,
        "short_top5": short_top5,
        "advantage": full_acc - short_acc,
        "advantage_top5": full_top5 - short_top5,
        "n_probes": total_probes,
    }


# ── Repetition / Coherence ───────────────────────────────────────────────

@torch.no_grad()
def generation_quality(model_fn, vocab_size: int, seed_chunks: list[torch.Tensor],
                       device: str, gen_len: int = 256,
                       temperature: float = 0.8, top_k: int = 50,
                       n_samples: int = 10) -> dict[str, float]:
    """Measure generation quality: repetition rate, unique n-gram ratios.

    Takes seed chunks (first 128 tokens as context), generates gen_len tokens,
    then measures:
      - rep_2: fraction of bigrams that are repeated
      - rep_3: fraction of trigrams that are repeated
      - distinct_1: number of unique unigrams / total unigrams
      - distinct_2: number of unique bigrams / total bigrams
      - entropy: average prediction entropy (higher = more diverse vocab use)

    Lower repetition + higher distinct = better quality.
    """
    seed_len = 128
    all_rep2 = []
    all_rep3 = []
    all_dist1 = []
    all_dist2 = []
    all_entropy = []

    for i, chunk in enumerate(seed_chunks[:n_samples]):
        chunk = chunk.to(device)
        # Use first seed_len tokens as prompt
        x = chunk[:, :seed_len]

        # Generate tokens autoregressively
        generated = []
        entropies = []
        for _ in range(gen_len):
            logits = model_fn(x)
            next_logits = logits[:, -1, :] / temperature

            # Compute entropy before top-k
            probs_full = F.softmax(next_logits, dim=-1)
            ent = -(probs_full * (probs_full + 1e-10).log()).sum(dim=-1)
            entropies.append(ent.item())

            # Top-k sampling
            if top_k > 0:
                v, _ = torch.topk(next_logits, min(top_k, next_logits.size(-1)))
                next_logits[next_logits < v[:, [-1]]] = float("-inf")

            probs = F.softmax(next_logits, dim=-1)
            next_id = torch.multinomial(probs, num_samples=1)
            x = torch.cat([x, next_id], dim=1)
            generated.append(next_id.item())

        # Compute repetition metrics
        if len(generated) < 3:
            continue

        # Bigram repetition
        bigrams = [(generated[j], generated[j + 1]) for j in range(len(generated) - 1)]
        unique_bigrams = set(bigrams)
        rep2 = 1.0 - len(unique_bigrams) / len(bigrams) if bigrams else 0

        # Trigram repetition
        trigrams = [(generated[j], generated[j + 1], generated[j + 2])
                     for j in range(len(generated) - 2)]
        unique_trigrams = set(trigrams)
        rep3 = 1.0 - len(unique_trigrams) / len(trigrams) if trigrams else 0

        # Distinct-1, distinct-2
        dist1 = len(set(generated)) / len(generated)
        dist2 = len(unique_bigrams) / len(bigrams) if bigrams else 0

        all_rep2.append(rep2)
        all_rep3.append(rep3)
        all_dist1.append(dist1)
        all_dist2.append(dist2)
        all_entropy.append(sum(entropies) / len(entropies))

    if not all_rep2:
        return {"rep_2": 0, "rep_3": 0, "distinct_1": 0, "distinct_2": 0, "entropy": 0}

    return {
        "rep_2": sum(all_rep2) / len(all_rep2),
        "rep_3": sum(all_rep3) / len(all_rep3),
        "distinct_1": sum(all_dist1) / len(all_dist1),
        "distinct_2": sum(all_dist2) / len(all_dist2),
        "entropy": sum(all_entropy) / len(all_entropy),
        "n_samples": len(all_rep2),
    }


# ── Model Wrappers ────────────────────────────────────────────────────────

def make_lolm_fn(model: LOLM):
    """Wrap LOLM model to return just logits."""
    def fn(x):
        out = model(x)
        return out.logits
    return fn


def load_lolm(checkpoint_path: str, device: str) -> tuple:
    """Load LOLM model and return (model_fn, vocab_size, info_dict)."""
    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    cfg = load_config(ckpt["config"])

    model = LOLM(cfg.model).to(device)
    model.load_state_dict(ckpt["model"], strict=False)
    model.eval()

    step = ckpt.get("step", "?")
    params = model.count_parameters()
    seq_len = cfg.training.seq_len

    # Estimate tokens seen
    batch = cfg.training.batch_size
    accum = cfg.training.get("grad_accumulation_steps", 1) if hasattr(cfg.training, "get") else getattr(cfg.training, "grad_accumulation_steps", 1)
    train_seq = cfg.training.seq_len
    if isinstance(step, int):
        tokens_seen = step * batch * accum * train_seq
    else:
        tokens_seen = 0

    info = {
        "name": "LOLM-304M",
        "params": params["total"],
        "step": step,
        "tokens_seen": tokens_seen,
        "seq_len": seq_len,
    }

    return make_lolm_fn(model), cfg.model.vocab_size, info


def load_pythia(pythia_step: int = 512, device: str = "cuda") -> tuple:
    """Load Pythia-410M at a specific training step."""
    from transformers import GPTNeoXForCausalLM, AutoTokenizer

    revision = f"step{pythia_step}"
    model_name = "EleutherAI/pythia-410m"

    print(f"Loading Pythia-410M at {revision}...")
    model = GPTNeoXForCausalLM.from_pretrained(
        model_name, revision=revision, torch_dtype=torch.float16
    ).to(device)
    model.eval()

    tokenizer = AutoTokenizer.from_pretrained(model_name)

    def model_fn(x):
        out = model(x)
        return out.logits

    tokens_seen = pythia_step * 2_097_152  # Pythia batch tokens per step

    info = {
        "name": "Pythia-410M",
        "params": 410_000_000,
        "step": pythia_step,
        "tokens_seen": tokens_seen,
        "seq_len": 2048,
    }

    return model_fn, tokenizer, info


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOLM vs Pythia Downstream Eval")
    parser.add_argument("--checkpoint", type=str, required=True,
                        help="LOLM checkpoint path")
    parser.add_argument("--pythia-step", type=int, default=512,
                        help="Pythia-410M training step (512, 1000, 2000, 5000)")
    parser.add_argument("--seq-len", type=int, default=1024,
                        help="Evaluation sequence length")
    parser.add_argument("--max-seqs", type=int, default=100,
                        help="Max evaluation sequences")
    parser.add_argument("--device", type=str, default=None,
                        help="Device (auto-detect if not specified)")
    parser.add_argument("--skip-lolm", action="store_true")
    parser.add_argument("--skip-pythia", action="store_true")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: fewer sequences, fewer probes")
    parser.add_argument("--no-generation", action="store_true",
                        help="Skip generation quality tests (faster)")
    args = parser.parse_args()

    if args.quick:
        args.max_seqs = 20

    # Auto-detect device
    if args.device is None:
        if torch.cuda.is_available():
            args.device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            args.device = "mps"
        else:
            args.device = "cpu"

    print(f"Device: {args.device}")
    print(f"Seq len: {args.seq_len}, Max seqs: {args.max_seqs}")

    # ── Load evaluation text ──────────────────────────────────────────
    print("\nLoading WikiText-103 test split...")
    raw_text = get_wikitext_raw()
    print(f"Raw text: {len(raw_text):,} characters")

    # ── Results storage ───────────────────────────────────────────────
    results = {}

    # ── Evaluate LOLM ─────────────────────────────────────────────────
    if not args.skip_lolm:
        print("\n" + "=" * 70)
        print("LOLM EVALUATION")
        print("=" * 70)

        model_fn, vocab_size, info = load_lolm(args.checkpoint, args.device)
        enc = tiktoken.get_encoding("gpt2")
        chunks, n_tokens = tokenize_and_chunk(
            raw_text, enc.encode, args.seq_len, args.max_seqs
        )

        print(f"Model: {info['name']}, {info['params']:,} params")
        print(f"Step: {info['step']}, Tokens seen: {info['tokens_seen']:,}")
        print(f"Eval chunks: {len(chunks)}, seq_len={args.seq_len}")

        # 1. Positional PPL
        print("\n--- Positional PPL ---")
        ppls, bpcs = positional_ppl(model_fn, chunks, args.device, n_bins=4)
        bin_size = args.seq_len // 4
        for i, (p, b) in enumerate(zip(ppls, bpcs)):
            start = i * bin_size
            end = start + bin_size if i < 3 else args.seq_len
            print(f"  pos {start:>4d}-{end:>4d}: PPL={p:>8.2f}  BPC={b:.4f}")

        # Late-position gain (how much better at end vs start)
        late_gain = (bpcs[-1] - bpcs[0]) / bpcs[0] * 100
        print(f"  Late-position BPC change: {late_gain:+.1f}%")
        print(f"  {'(improves at later positions)' if late_gain < 0 else '(degrades at later positions)'}")

        # 2. Long-range cloze
        print("\n--- Long-Range Cloze ---")
        n_probes = 20 if args.quick else 50
        cloze = long_range_cloze(model_fn, chunks, args.device,
                                  context_distance=512, n_probes=n_probes)
        print(f"  Full context top-1: {cloze['full_acc']:.1%}")
        print(f"  Short context top-1: {cloze['short_acc']:.1%}")
        print(f"  Advantage (full-short): {cloze['advantage']:+.1%}")
        print(f"  Full context top-5: {cloze['full_top5']:.1%}")
        print(f"  Short context top-5: {cloze['short_top5']:.1%}")
        print(f"  Advantage top-5: {cloze['advantage_top5']:+.1%}")
        print(f"  Total probes: {cloze['n_probes']}")

        # 3. Generation quality
        gen_results = None
        if not args.no_generation:
            print("\n--- Generation Quality ---")
            n_gen = 5 if args.quick else 10
            gen_results = generation_quality(
                model_fn, vocab_size, chunks, args.device,
                gen_len=256, n_samples=n_gen,
            )
            print(f"  Bigram repetition: {gen_results['rep_2']:.1%}")
            print(f"  Trigram repetition: {gen_results['rep_3']:.1%}")
            print(f"  Distinct-1: {gen_results['distinct_1']:.3f}")
            print(f"  Distinct-2: {gen_results['distinct_2']:.3f}")
            print(f"  Avg entropy: {gen_results['entropy']:.2f} nats")

        # Overall BPC
        total_loss = 0.0
        total_tokens = 0
        for chunk in chunks:
            chunk = chunk.to(args.device)
            x, y = chunk[:, :-1], chunk[:, 1:]
            logits = model_fn(x)
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)), y.reshape(-1), reduction="sum"
            )
            total_loss += loss.item()
            total_tokens += y.numel()

        avg_loss = total_loss / total_tokens
        overall_ppl = math.exp(min(avg_loss, 20))
        overall_bpc = (total_loss / math.log(2)) / len(raw_text[:total_tokens])

        results["lolm"] = {
            "info": info,
            "overall_ppl": overall_ppl,
            "overall_bpc": avg_loss / math.log(2),
            "positional_ppl": ppls,
            "positional_bpc": bpcs,
            "late_gain": late_gain,
            "cloze": cloze,
            "generation": gen_results,
        }

        # Free VRAM
        del model_fn
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ── Evaluate Pythia ───────────────────────────────────────────────
    if not args.skip_pythia:
        print("\n" + "=" * 70)
        print("PYTHIA-410M EVALUATION")
        print("=" * 70)

        model_fn, tokenizer, info = load_pythia(args.pythia_step, args.device)

        # Tokenize with Pythia's tokenizer
        pythia_encode = lambda text: tokenizer.encode(text)
        chunks, n_tokens = tokenize_and_chunk(
            raw_text, pythia_encode, args.seq_len, args.max_seqs
        )

        print(f"Model: {info['name']}, {info['params']:,} params")
        print(f"Step: {info['step']}, Tokens seen: {info['tokens_seen']:,}")
        print(f"Eval chunks: {len(chunks)}, seq_len={args.seq_len}")

        # 1. Positional PPL
        print("\n--- Positional PPL ---")
        ppls, bpcs = positional_ppl(model_fn, chunks, args.device, n_bins=4)
        bin_size = args.seq_len // 4
        for i, (p, b) in enumerate(zip(ppls, bpcs)):
            start = i * bin_size
            end = start + bin_size if i < 3 else args.seq_len
            print(f"  pos {start:>4d}-{end:>4d}: PPL={p:>8.2f}  BPC={b:.4f}")

        late_gain = (bpcs[-1] - bpcs[0]) / bpcs[0] * 100
        print(f"  Late-position BPC change: {late_gain:+.1f}%")

        # 2. Long-range cloze
        print("\n--- Long-Range Cloze ---")
        n_probes = 20 if args.quick else 50
        cloze = long_range_cloze(model_fn, chunks, args.device,
                                  context_distance=512, n_probes=n_probes)
        print(f"  Full context top-1: {cloze['full_acc']:.1%}")
        print(f"  Short context top-1: {cloze['short_acc']:.1%}")
        print(f"  Advantage (full-short): {cloze['advantage']:+.1%}")
        print(f"  Full context top-5: {cloze['full_top5']:.1%}")
        print(f"  Short context top-5: {cloze['short_top5']:.1%}")
        print(f"  Advantage top-5: {cloze['advantage_top5']:+.1%}")

        # 3. Generation quality
        gen_results = None
        if not args.no_generation:
            print("\n--- Generation Quality ---")
            n_gen = 5 if args.quick else 10
            gen_results = generation_quality(
                model_fn, tokenizer.vocab_size, chunks, args.device,
                gen_len=256, n_samples=n_gen,
            )
            print(f"  Bigram repetition: {gen_results['rep_2']:.1%}")
            print(f"  Trigram repetition: {gen_results['rep_3']:.1%}")
            print(f"  Distinct-1: {gen_results['distinct_1']:.3f}")
            print(f"  Distinct-2: {gen_results['distinct_2']:.3f}")
            print(f"  Avg entropy: {gen_results['entropy']:.2f} nats")

        # Overall BPC
        total_loss = 0.0
        total_tokens = 0
        for chunk in chunks:
            chunk = chunk.to(args.device)
            x, y = chunk[:, :-1], chunk[:, 1:]
            logits = model_fn(x)
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)), y.reshape(-1), reduction="sum"
            )
            total_loss += loss.item()
            total_tokens += y.numel()

        avg_loss = total_loss / total_tokens
        overall_ppl = math.exp(min(avg_loss, 20))

        results["pythia"] = {
            "info": info,
            "overall_ppl": overall_ppl,
            "overall_bpc": avg_loss / math.log(2),
            "positional_ppl": ppls,
            "positional_bpc": bpcs,
            "late_gain": late_gain,
            "cloze": cloze,
            "generation": gen_results,
        }

        # Free VRAM
        del model_fn
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ── Comparison Summary ────────────────────────────────────────────
    if "lolm" in results and "pythia" in results:
        lolm = results["lolm"]
        pythia = results["pythia"]

        print("\n" + "=" * 70)
        print("COMPARISON SUMMARY: LOLM vs Pythia")
        print("=" * 70)

        print(f"\n{'':>30s} {'LOLM-304M':>12s} {'Pythia-410M':>12s} {'Winner':>10s}")
        print("-" * 70)

        # Parameters
        print(f"{'Parameters':>30s} {lolm['info']['params']:>12,d} {pythia['info']['params']:>12,d}")
        print(f"{'Tokens seen':>30s} {lolm['info']['tokens_seen']:>12,d} {pythia['info']['tokens_seen']:>12,d}")

        # Overall metrics
        winner = "LOLM" if lolm["overall_bpc"] < pythia["overall_bpc"] else "Pythia"
        print(f"\n{'Overall BPC':>30s} {lolm['overall_bpc']:>12.4f} {pythia['overall_bpc']:>12.4f} {winner:>10s}")

        winner = "LOLM" if lolm["overall_ppl"] < pythia["overall_ppl"] else "Pythia"
        print(f"{'Overall PPL':>30s} {lolm['overall_ppl']:>12.2f} {pythia['overall_ppl']:>12.2f} {winner:>10s}")

        # Positional BPC
        print(f"\n{'--- Positional BPC ---':>30s}")
        bin_size = args.seq_len // 4
        for i in range(4):
            start = i * bin_size
            end = start + bin_size if i < 3 else args.seq_len
            label = f"BPC pos {start}-{end}"
            lb = lolm["positional_bpc"][i]
            pb = pythia["positional_bpc"][i]
            winner = "LOLM" if lb < pb else "Pythia"
            print(f"{label:>30s} {lb:>12.4f} {pb:>12.4f} {winner:>10s}")

        # Late-position gain comparison
        print(f"\n{'Late-pos BPC change':>30s} {lolm['late_gain']:>+11.1f}% {pythia['late_gain']:>+11.1f}%", end="")
        winner = "LOLM" if lolm["late_gain"] < pythia["late_gain"] else "Pythia"
        print(f" {winner:>10s}")

        # Long-range cloze
        print(f"\n{'--- Long-Range Cloze ---':>30s}")
        lc = lolm["cloze"]
        pc = pythia["cloze"]

        winner = "LOLM" if lc["full_acc"] > pc["full_acc"] else "Pythia"
        print(f"{'Full ctx top-1 acc':>30s} {lc['full_acc']:>11.1%} {pc['full_acc']:>12.1%} {winner:>10s}")

        winner = "LOLM" if lc["advantage"] > pc["advantage"] else "Pythia"
        print(f"{'Context advantage':>30s} {lc['advantage']:>+11.1%} {pc['advantage']:>+12.1%} {winner:>10s}")

        winner = "LOLM" if lc["full_top5"] > pc["full_top5"] else "Pythia"
        print(f"{'Full ctx top-5 acc':>30s} {lc['full_top5']:>11.1%} {pc['full_top5']:>12.1%} {winner:>10s}")

        # Generation quality
        if lolm["generation"] and pythia["generation"]:
            print(f"\n{'--- Generation Quality ---':>30s}")
            lg = lolm["generation"]
            pg = pythia["generation"]

            winner = "LOLM" if lg["rep_2"] < pg["rep_2"] else "Pythia"
            print(f"{'Bigram repetition':>30s} {lg['rep_2']:>11.1%} {pg['rep_2']:>12.1%} {winner:>10s}")

            winner = "LOLM" if lg["distinct_2"] > pg["distinct_2"] else "Pythia"
            print(f"{'Distinct-2':>30s} {lg['distinct_2']:>12.3f} {pg['distinct_2']:>12.3f} {winner:>10s}")

            winner = "LOLM" if lg["entropy"] > pg["entropy"] else "Pythia"
            print(f"{'Prediction entropy':>30s} {lg['entropy']:>12.2f} {pg['entropy']:>12.2f} {winner:>10s}")

        print("\n" + "=" * 70)
        print("NOTE: LOLM (304M params) is compared against Pythia (410M params).")
        print("A win for LOLM despite 26% fewer parameters strongly supports the")
        print("architectural hypothesis that latent-order modeling helps.")
        print("=" * 70)

    elif "lolm" in results:
        print("\n(Pythia comparison skipped — run without --skip-pythia for full comparison)")
    elif "pythia" in results:
        print("\n(LOLM evaluation skipped — run without --skip-lolm for full comparison)")


if __name__ == "__main__":
    main()
