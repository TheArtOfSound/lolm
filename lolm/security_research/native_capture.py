"""Read-only telemetry extraction from a native LOLM checkpoint.

Different from a Qwen+LOLM-NFET graft: hidden drift comes from the
native model's surface representation h, not corrected graft hidden states.
Never claim identical metric semantics across architectures.

Model and tokenizer are injected for tests; actual local weight loading is
in scripts/capture_security_lolm_native.py. No network or execution tools.
"""
from __future__ import annotations
from typing import Any, Sequence

from .lab import Event
from .observer import NFETToken, security_event_hash, trace_digest, HEX256
from .capture import synthetic_prompt


def capture_native(events: Sequence[Event], model: Any, tokenizer: Any,
                   *, checkpoint_sha256: str, device: str = "cpu",
                   run_seed: int = 20261115, max_tokens: int = 64,
                   ) -> tuple[list[NFETToken], dict[str, Any]]:
    import torch

    if not isinstance(checkpoint_sha256, str) or not HEX256.fullmatch(checkpoint_sha256):
        raise ValueError("checkpoint SHA-256 must be independently pinned lowercase hex")
    if not isinstance(run_seed, int) or type(run_seed) is bool:
        raise ValueError("run_seed must be integer")
    if device not in {"cpu", "mps", "cuda"}:
        raise ValueError("device must be cpu, mps or cuda")
    if not 2 <= max_tokens <= 128:
        raise ValueError("max_tokens must be 2..128")
    if not events or len(events) > 200:
        raise ValueError("capture requires 1..200 fictional events")
    if any(e.source != "synthetic" for e in events):
        raise ValueError("native capture accepts fictional synthetic events only")

    model.eval()
    tokens: list[NFETToken] = []
    with torch.inference_mode():
        for event_index, event in enumerate(events):
            prompt = synthetic_prompt(event)
            ids = tokenizer.encode(prompt)
            if not isinstance(ids, list) or not 2 <= len(ids) <= max_tokens:
                raise ValueError("tokenizer must return bounded nonempty integer IDs")
            if any(type(x) is not int or x < 0 for x in ids):
                raise ValueError("invalid tokenizer IDs")
            # Regime Gumbel stochasticity is seeded per event. Identical
            # seed/platform/checkpoint should reproduce; hardware may vary.
            torch.manual_seed(run_seed + event_index)
            if device == "cuda":
                torch.cuda.manual_seed_all(run_seed + event_index)
            ids_tensor = torch.tensor([ids], dtype=torch.long, device=device)
            result = model(ids_tensor)
            logits = getattr(result, "logits", None)
            h = getattr(result, "h", None)
            gate = getattr(result, "gate_values", None)
            regimes = getattr(result, "regime_probs", None)
            if any(t is None for t in (logits, h, gate, regimes)):
                raise RuntimeError("native LOLM must expose logits, h, gate_values and regime_probs")
            seq_len = len(ids)
            if logits.ndim != 3 or logits.shape[:2] != (1, seq_len):
                raise RuntimeError("unexpected native logits shape")
            if h.ndim != 3 or h.shape[:2] != (1, seq_len):
                raise RuntimeError("unexpected native h shape")
            if gate.ndim != 3 or gate.shape[:2] != (1, seq_len):
                raise RuntimeError("unexpected native gate shape")
            if regimes.ndim != 3 or regimes.shape[:2] != (1, seq_len):
                raise RuntimeError("unexpected native regime shape")
            lprobs = torch.log_softmax(logits.float(), dim=-1)
            entropies = -(lprobs.exp() * lprobs).sum(-1)[0]
            for token_index in range(seq_len):
                drift = (
                    (h[0, token_index].float() - h[0, token_index-1].float()).square().mean()
                    if token_index > 0 else torch.tensor(0.0, device=h.device)
                )
                gp = gate[0, token_index].float().mean()
                ps = regimes[0, token_index].float().clamp_min(1e-8)
                reg_entropy = -(ps * ps.log()).sum()
                raw = dict(
                    event_index=event_index, token_index=token_index,
                    logit_entropy=float(entropies[token_index].item()),
                    hidden_drift=float(drift.item()),
                    gate_mean=float(gp.item()),
                    regime_entropy=float(reg_entropy.item()),
                )
                tokens.append(NFETToken.parse(raw))
    return tokens, {
        "schema": "lolm-nfet-observer/v1",
        "source_type": "checkpoint-generated",
        "runner": "lolm.model.LOLM/native_forward",
        "model_family": "native-lolm",
        "data_origin": "synthetic",
        "hidden_drift_definition": "surface_h_lag1_mse_not_graft_corrected_hidden",
        "regime_sampling_seeded_per_event": True,
        "run_seed": run_seed,
        "tokenizer": "caller supplied; exact tokenizer recorded by script",
        "checkpoint_sha256": checkpoint_sha256,
        "events_sha256": security_event_hash(events),
        "trace_sha256": trace_digest(tokens),
        "trace_origin_attested": False,
    }
