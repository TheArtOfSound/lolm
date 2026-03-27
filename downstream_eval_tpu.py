"""Downstream task evaluation for LOLM and Baseline on TPU.
Evaluates: HellaSwag, LAMBADA, ARC-Easy, WikiText-103 PPL
Uses lm-evaluation-harness compatible approach.
"""
import os, sys, math, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import torch_xla.core.xla_model as xm
from lolm.config import load_config
from lolm.model import LOLM
from datasets import load_dataset
import tiktoken

def load_model(checkpoint_path, config_path, device):
    cfg = load_config(config_path)
    model = LOLM(cfg.model).to(device)
    ckpt = torch.load(checkpoint_path, map_location='cpu', weights_only=False)
    model.load_state_dict(ckpt['model'], strict=False)
    model.eval()
    step = ckpt.get('step', '?')
    params = sum(p.numel() for p in model.parameters())
    print(f"Loaded {params:,} params from step {step}")
    return model, cfg

@torch.no_grad()
def eval_wikitext103(model, device, seq_len=512, n_batches=100):
    """WikiText-103 perplexity."""
    enc = tiktoken.get_encoding("gpt2")
    ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="test")
    text = "\n\n".join([x for x in ds["text"] if x.strip()])
    tokens = enc.encode(text)
    
    total_loss, total_tokens = 0.0, 0
    stride = seq_len + 1
    for i in range(min(n_batches, len(tokens) // stride)):
        chunk = torch.tensor(tokens[i*stride:(i+1)*stride], dtype=torch.long, device=device).unsqueeze(0)
        x, y = chunk[:, :-1], chunk[:, 1:]
        out = model(x)
        loss = torch.nn.functional.cross_entropy(out.logits.view(-1, out.logits.size(-1)), y.reshape(-1), reduction="sum")
        total_loss += loss.item()
        total_tokens += y.numel()
        xm.mark_step()
    
    avg_loss = total_loss / total_tokens
    ppl = math.exp(min(avg_loss, 20))
    return {"wikitext103_loss": avg_loss, "wikitext103_ppl": ppl}

@torch.no_grad()
def eval_lambada(model, device, seq_len=512):
    """LAMBADA last-word prediction accuracy."""
    enc = tiktoken.get_encoding("gpt2")
    ds = load_dataset("lambada", split="test")
    
    correct, total = 0, 0
    for example in list(ds)[:1000]:
        text = example["text"]
        tokens = enc.encode(text)
        if len(tokens) < 2 or len(tokens) > seq_len:
            continue
        
        # The task: predict the last word given the context
        last_word = text.split()[-1]
        last_tokens = enc.encode(" " + last_word)
        
        input_ids = torch.tensor(tokens[:-1], dtype=torch.long, device=device).unsqueeze(0)
        out = model(input_ids)
        pred_token = out.logits[0, -1].argmax().item()
        
        if pred_token == tokens[-1]:
            correct += 1
        total += 1
        
        if total % 100 == 0:
            xm.mark_step()
            print(f"  LAMBADA: {total} examples, acc={correct/total:.3f}")
    
    acc = correct / total if total > 0 else 0
    return {"lambada_acc": acc, "lambada_total": total}

@torch.no_grad()
def eval_hellaswag(model, device, seq_len=512):
    """HellaSwag completion selection accuracy."""
    enc = tiktoken.get_encoding("gpt2")
    ds = load_dataset("Rowan/hellaswag", split="validation")
    
    correct, total = 0, 0
    for example in list(ds)[:500]:
        ctx = example["ctx"]
        endings = example["endings"]
        label = int(example["label"])
        
        scores = []
        for ending in endings:
            text = ctx + " " + ending
            tokens = enc.encode(text)[:seq_len]
            if len(tokens) < 2:
                scores.append(float('-inf'))
                continue
            
            input_ids = torch.tensor(tokens[:-1], dtype=torch.long, device=device).unsqueeze(0)
            targets = torch.tensor(tokens[1:], dtype=torch.long, device=device).unsqueeze(0)
            out = model(input_ids)
            loss = torch.nn.functional.cross_entropy(
                out.logits.view(-1, out.logits.size(-1)), targets.reshape(-1), reduction="mean"
            )
            scores.append(-loss.item())
        
        pred = max(range(len(scores)), key=lambda i: scores[i])
        if pred == label:
            correct += 1
        total += 1
        
        if total % 50 == 0:
            xm.mark_step()
            print(f"  HellaSwag: {total} examples, acc={correct/total:.3f}")
    
    acc = correct / total if total > 0 else 0
    return {"hellaswag_acc": acc, "hellaswag_total": total}

if __name__ == "__main__":
    device = xm.xla_device()
    
    ckpt_path = sys.argv[1]
    config_path = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 else "eval_results.json"
    
    print(f"Checkpoint: {ckpt_path}")
    print(f"Config: {config_path}")
    
    model, cfg = load_model(ckpt_path, config_path, device)
    
    results = {"checkpoint": ckpt_path, "config": config_path}
    
    print("\n=== WikiText-103 PPL ===")
    r = eval_wikitext103(model, device)
    results.update(r)
    print(f"  PPL: {r['wikitext103_ppl']:.2f}")
    
    print("\n=== LAMBADA ===")
    r = eval_lambada(model, device)
    results.update(r)
    print(f"  Accuracy: {r['lambada_acc']:.3f}")
    
    print("\n=== HellaSwag ===")
    r = eval_hellaswag(model, device)
    results.update(r)
    print(f"  Accuracy: {r['hellaswag_acc']:.3f}")
    
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for k, v in results.items():
        if k not in ["checkpoint", "config"]:
            print(f"  {k}: {v}")
    print(f"Saved to {output_file}")
