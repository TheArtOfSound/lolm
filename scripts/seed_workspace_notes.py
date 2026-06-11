"""Seed the workspace memory with the LOLM/NFET knowledge pack.

One source of truth for the facts the agent can retrieve. Used by the replay
recorder and by deployment (idempotent — existing notes are not duplicated).

Usage:
    PYTHONPATH=. python scripts/seed_workspace_notes.py            # default data dir
    LOCAL_UI_DATA_DIR=/opt/apps/lolm/local_ui/data PYTHONPATH=. \
        python scripts/seed_workspace_notes.py
"""

from __future__ import annotations

# (text, tag, importance) — facts only; numbers match the README results.
NOTES = [
    # Architecture
    ("LOLM fuses five streams: surface decoder h, latent SSM z, regime layer r, persistent memory m, and a manifestation gate g that arbitrates surface vs latent per dimension.", "research", 5),
    ("The fusion equation is o_t = g*LN(W_h h_t) + (1-g)*LN(W_z z_t) + W_m m_t + W_r r_t — per-dimension gating with branch normalization to prevent magnitude mismatch.", "research", 5),
    ("The surface decoder is a pre-norm Transformer with rotary position embeddings; it handles local token relationships and fluent prose.", "research", 4),
    ("The latent SSM core is a selective state-space model (Mamba-style) with a parallel scan; it tracks slow latent dynamics beneath the words.", "research", 5),
    ("The regime layer detects discrete phases with Gumbel-Softmax over 64 codes plus causal conv1d neighbor interaction; gradient isolation keeps all 64 codes alive at 1.57B scale.", "research", 5),
    ("Persistent memory has three banks — episodic, semantic, and self — with gated chunked read/write so gradients flow through cross-sequence state.", "research", 4),
    ("The manifestation gate is a per-dimension sigmoid from a 2-layer MLP deciding, feature by feature, whether the surface or latent stream speaks; its learned equilibrium sits near 0.72.", "research", 5),
    # Results
    ("At 1.57B parameters on H200, LOLM reaches 33.2 perplexity vs 39.1 for a parameter-matched decoder-only baseline at step ~24K — a 15 percent improvement on FineWeb-Edu.", "research", 5),
    ("LOLM-304M beats Pythia-410M on WikiText-103: eval perplexity 68.4 vs 142.9 with 26 percent fewer parameters; late-position bits-per-character 1.02 vs 1.23.", "research", 5),
    ("On Google TPU v4, LOLM converges up to 43 percent faster than a matched baseline in early training; the baseline catches up around step 15-20K.", "research", 4),
    ("Dependency inversion: the latent SSM path is only ~29 percent of the fused representation, but forcing the gate to surface-only explodes perplexity from 34.47 to 485 million — a 14,000,000x increase.", "research", 5),
    ("Inference-time component ablation at 304M: full LOLM 59.2 PPL; no regime layer +109 percent; no SSM +744 percent; no gate +905 percent; decoder only +3,612 percent. Every stream earns its place.", "research", 4),
    ("LOLM trains with 7 complementary losses: token cross-entropy, contrastive predictive coding, changepoint alignment, regime diversity, competitive gate, memory focus, and a gate regularizer.", "research", 4),
    # NFET agent
    ("NFET stands for Noise-Driven Functional Emergence Theory, by Bryan and Brandyn Leonard at Qira LLC.", "research", 4),
    ("The NFET controller maps four measured observables — logit entropy, hidden drift, gate mean, regime entropy — to five controls: continue, retrieve, verify, branch, finalize.", "research", 5),
    ("Logit entropy measures next-token uncertainty; hidden drift measures how fast the corrected hidden state moves between tokens (lag-1 across streamed tokens).", "research", 4),
    ("The agent decides at segment boundaries: sustained entropy spikes trigger retrieval of evidence, drift spikes trigger a verification pass, regime collapse triggers branching, and calm confidence triggers finalize.", "research", 5),
    ("The control policy calibrates against the run's own history using rolling z-scores with pre-batch baseline snapshots and std floors, so it adapts to any backbone without per-model tuning.", "research", 4),
    ("The control head trains on the workspace's own logged traffic: first distilled from the calibrated heuristic, then corrected by outcome labels mined from run receipts — retrieves that found nothing are relabeled as continue.", "research", 5),
    ("Provenance is assembled by the harness from the action log, never written by the model — the agent cannot misreport what it did. The model writes only the answer prose.", "research", 5),
    ("Every agent run produces a proof receipt comparing the same question answered in plain base mode, with verdicts like nfet_control_visible or an honest no_visible_difference.", "research", 4),
    # Product / meta
    ("The LOLM-NFET graft rides on frozen open backbones (Qwen3 0.6B to 32B targets); a hybrid mode lets the local latent machinery monitor a frontier model while it does the writing.", "product", 4),
    ("The live demo at lolm.imagineqira.com runs Qwen3-0.6B with the LOLM graft and trained NFET control head on a shared 2-vCPU server — the point is the decision machinery, not the prose of a 0.6B model.", "product", 4),
    ("The npm package lolm-nfet-client provides a zero-dependency JS client for the agent's SSE protocol: runAgent, playReplay, friendly narration, and getStatus.", "product", 3),
    ("LOLM is patent pending (provisional application 64002166, Qira LLC) and code is available under the LOLM Community License — free for research, education, and small entities.", "product", 4),
]


def seed(memory) -> int:
    """Idempotently add the knowledge pack to a MemoryStore. Returns #added."""
    added = 0
    for text, tag, importance in NOTES:
        probe = " ".join(text.split()[:6])
        if not memory.search_notes(probe, limit=1):
            memory.append_note(text, tag=tag, importance=importance)
            added += 1
    return added


if __name__ == "__main__":
    import os
    from pathlib import Path

    from local_ui.memory_store import MemoryStore

    root = Path(os.environ.get("LOCAL_UI_DATA_DIR", "local_ui/data"))
    store = MemoryStore(root)
    count = seed(store)
    print(f"seeded {count} new notes ({len(NOTES)} in pack) into {root}")
