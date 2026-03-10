#!/usr/bin/env python3
"""
Evaluate public baseline models on standard benchmarks.
Runs alongside LOLM 1.57B training (inference only, ~5-8 GB VRAM).

Models evaluated:
  - Cerebras-GPT-1.3B  (GPT-2 tokenizer, Chinchilla-optimal, The Pile)
  - Cerebras-GPT-2.7B  (GPT-2 tokenizer, Chinchilla-optimal, The Pile)
  - OPT-1.3B           (GPT-2 tokenizer, BookCorpus+CC+Wiki+Reddit)

Benchmarks:
  - WikiText-2 test set  (standard, many published numbers)
  - FineWeb-Edu sample   (matches LOLM training distribution)

Methodology: sliding-window PPL with stride = seq_len // 2
(follows HuggingFace best practice for fixed-length models)
"""
from __future__ import annotations

import json
import time
import torch
import numpy as np
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────
MODELS = [
    "cerebras/Cerebras-GPT-1.3B",
    "cerebras/Cerebras-GPT-2.7B",
    "facebook/opt-1.3b",
]

MAX_SEQ_LEN = 2048
STRIDE = 1024  # sliding window stride = seq_len // 2
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.bfloat16 if torch.cuda.is_available() else torch.float32
FINEWEB_SAMPLE_TOKENS = 200_000  # ~200K tokens from FineWeb-Edu for eval

RESULTS_FILE = "baseline_eval_results.json"


def get_wikitext2():
    """Load WikiText-2 test set."""
    from datasets import load_dataset
    print("  Loading WikiText-2 test set...")
    ds = load_dataset("wikitext", "wikitext-2-raw-v1", split="test")
    text = "\n\n".join([t for t in ds["text"] if t.strip()])
    return text


def get_fineweb_sample(tokenizer, n_tokens=200_000):
    """Load a small FineWeb-Edu sample for eval (streaming, no full download)."""
    from datasets import load_dataset
    print(f"  Loading FineWeb-Edu sample (~{n_tokens:,} tokens)...")
    ds = load_dataset(
        "HuggingFaceFW/fineweb-edu",
        name="sample-10BT",
        split="train",
        streaming=True,
    )

    texts = []
    total_tokens = 0
    for example in ds:
        text = example.get("text", "")
        if not text.strip():
            continue
        # Rough estimate: 1 token ≈ 4 chars
        est_tokens = len(text) // 4
        texts.append(text)
        total_tokens += est_tokens
        if total_tokens >= n_tokens:
            break

    combined = "\n\n".join(texts)
    # Verify actual token count
    enc = tokenizer(combined, return_tensors="pt")
    actual_tokens = enc.input_ids.shape[1]
    print(f"  FineWeb-Edu sample: {len(texts)} docs, {actual_tokens:,} tokens")
    return combined


def sliding_window_ppl(model, tokenizer, text, max_len=2048, stride=1024):
    """
    Compute perplexity using sliding window approach.
    Following HuggingFace methodology:
    https://huggingface.co/docs/transformers/perplexity
    """
    encodings = tokenizer(text, return_tensors="pt")
    input_ids = encodings.input_ids.to(DEVICE)
    seq_len = input_ids.size(1)

    print(f"    Sequence length: {seq_len:,} tokens")
    print(f"    Windows: ~{max(1, (seq_len - max_len) // stride + 1)}")

    nlls = []
    n_tokens_scored = 0
    prev_end = 0
    t0 = time.time()

    for begin in range(0, seq_len, stride):
        end = min(begin + max_len, seq_len)
        target_len = end - prev_end  # only score the new tokens

        input_chunk = input_ids[:, begin:end]
        target_chunk = input_chunk.clone()
        # Mask out tokens we already scored (overlap region)
        target_chunk[:, :-target_len] = -100

        with torch.no_grad():
            with torch.amp.autocast("cuda", dtype=DTYPE):
                outputs = model(input_chunk, labels=target_chunk)
                neg_log_likelihood = outputs.loss

        # outputs.loss is mean over non-masked tokens
        nlls.append(neg_log_likelihood.item() * target_len)
        n_tokens_scored += target_len
        prev_end = end

        if end == seq_len:
            break

    elapsed = time.time() - t0
    mean_nll = sum(nlls) / n_tokens_scored
    ppl = np.exp(mean_nll)

    print(f"    Tokens scored: {n_tokens_scored:,}")
    print(f"    Cross-entropy: {mean_nll:.4f}")
    print(f"    Perplexity: {ppl:.2f}")
    print(f"    Time: {elapsed:.1f}s")

    return {
        "cross_entropy": round(mean_nll, 4),
        "perplexity": round(ppl, 2),
        "tokens_scored": n_tokens_scored,
        "time_seconds": round(elapsed, 1),
    }


def evaluate_model(model_name, benchmarks):
    """Evaluate a single model on all benchmarks."""
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"\n{'='*70}")
    print(f"MODEL: {model_name}")
    print(f"{'='*70}")

    # Load model
    print(f"  Loading model...")
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=DTYPE,
    ).to(DEVICE)
    model.eval()

    # Count params
    n_params = sum(p.numel() for p in model.parameters())
    load_time = time.time() - t0

    # Check VRAM
    if torch.cuda.is_available():
        vram_gb = torch.cuda.memory_allocated() / 1e9
        print(f"  Loaded: {n_params/1e9:.2f}B params, {vram_gb:.1f} GB VRAM, {load_time:.1f}s")
    else:
        print(f"  Loaded: {n_params/1e9:.2f}B params, {load_time:.1f}s")

    results = {
        "model": model_name,
        "params": n_params,
        "params_B": round(n_params / 1e9, 3),
        "dtype": str(DTYPE),
        "benchmarks": {},
    }

    # Evaluate on each benchmark
    for bench_name, bench_text in benchmarks.items():
        print(f"\n  Benchmark: {bench_name}")
        print(f"  {'-'*50}")

        bench_result = sliding_window_ppl(
            model, tokenizer, bench_text,
            max_len=MAX_SEQ_LEN, stride=STRIDE,
        )
        results["benchmarks"][bench_name] = bench_result

    # Free VRAM
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return results


def main():
    print("=" * 70)
    print("LOLM Baseline Evaluation Suite")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Device: {DEVICE}, dtype: {DTYPE}")
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name()
        total = torch.cuda.get_device_properties(0).total_memory / 1e9
        used = torch.cuda.memory_allocated() / 1e9
        print(f"GPU: {name}, {total:.0f} GB total, {used:.1f} GB used")
    print("=" * 70)

    # Load benchmarks once (they're small, stay on CPU)
    print("\n── Loading Benchmarks ──")

    # We need a tokenizer for FineWeb sampling — use GPT-2 since all models share it
    from transformers import AutoTokenizer
    gpt2_tok = AutoTokenizer.from_pretrained("gpt2")

    benchmarks = {}

    # WikiText-2
    wt2_text = get_wikitext2()
    benchmarks["wikitext2"] = wt2_text
    wt2_tokens = len(gpt2_tok(wt2_text)["input_ids"])
    print(f"  WikiText-2: {wt2_tokens:,} tokens")

    # FineWeb-Edu sample
    fwe_text = get_fineweb_sample(gpt2_tok, n_tokens=FINEWEB_SAMPLE_TOKENS)
    benchmarks["fineweb_edu"] = fwe_text

    # Evaluate each model
    all_results = []
    for model_name in MODELS:
        try:
            result = evaluate_model(model_name, benchmarks)
            all_results.append(result)

            # Save incrementally
            with open(RESULTS_FILE, "w") as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "config": {
                        "max_seq_len": MAX_SEQ_LEN,
                        "stride": STRIDE,
                        "dtype": str(DTYPE),
                        "device": DEVICE,
                        "fineweb_sample_tokens": FINEWEB_SAMPLE_TOKENS,
                    },
                    "results": all_results,
                }, f, indent=2)
            print(f"\n  ✓ Results saved to {RESULTS_FILE}")

        except Exception as e:
            print(f"\n  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({"model": model_name, "error": str(e)})

    # Print summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Model':<30} {'Params':>8} {'WT2 PPL':>10} {'WT2 xent':>10} {'FWE PPL':>10} {'FWE xent':>10}")
    print("-" * 80)

    for r in all_results:
        if "error" in r:
            print(f"{r['model']:<30} {'FAILED':>8}")
            continue

        name = r["model"].split("/")[-1]
        params = f"{r['params_B']:.1f}B"

        wt2 = r["benchmarks"].get("wikitext2", {})
        fwe = r["benchmarks"].get("fineweb_edu", {})

        wt2_ppl = f"{wt2.get('perplexity', 'N/A'):>10}" if wt2 else f"{'N/A':>10}"
        wt2_xent = f"{wt2.get('cross_entropy', 'N/A'):>10}" if wt2 else f"{'N/A':>10}"
        fwe_ppl = f"{fwe.get('perplexity', 'N/A'):>10}" if fwe else f"{'N/A':>10}"
        fwe_xent = f"{fwe.get('cross_entropy', 'N/A'):>10}" if fwe else f"{'N/A':>10}"

        print(f"{name:<30} {params:>8} {wt2_ppl} {wt2_xent} {fwe_ppl} {fwe_xent}")

    print(f"\nDone: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Results: {RESULTS_FILE}")

    # Print what LOLM needs to beat
    print("\n── LOLM Targets ──")
    print("To claim 'beats Chinchilla-optimal at 1.7x params':")
    print("  LOLM-1.57B must beat Cerebras-GPT-2.7B on BOTH benchmarks")
    print("To claim 'beats same-class decoder':")
    print("  LOLM-1.57B must beat OPT-1.3B and Cerebras-GPT-1.3B")


if __name__ == "__main__":
    main()
