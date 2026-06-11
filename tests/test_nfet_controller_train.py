from __future__ import annotations

import torch

from lolm.nfet_controller_train import (
    build_dataset,
    save_controller_checkpoint,
    synth_scenarios,
    train_control_head,
)
from lolm.nfet_graft import LOLMNFETGraft
from lolm.nfet_policy import CONTROL_LABELS


def small_graft(d_model: int = 32) -> LOLMNFETGraft:
    torch.manual_seed(3)
    return LOLMNFETGraft(d_model=d_model, n_regimes=8, latent_backend="gru_debug")


def test_synth_scenarios_have_event_diversity():
    sequences = synth_scenarios(40, seq_len=160, seed=1)
    assert len(sequences) == 40
    dataset = build_dataset(sequences, d_model=32, seed=1)
    # all five classes should appear in the weak labels
    assert all(count > 0 for count in dataset.class_counts), dataset.class_counts
    assert dataset.features.shape[1] == 32 + 4


def test_bootstrap_training_distills_heuristic(tmp_path):
    graft = small_graft()
    sequences = synth_scenarios(200, seq_len=160, seed=2)
    dataset = build_dataset(sequences, d_model=32, seed=2)
    metrics = train_control_head(graft, dataset, epochs=25, lr=2e-3,
                                 batch_size=64, seed=2)
    assert metrics["val_acc"] >= 0.7, metrics
    # loss went down
    history = metrics["history"]
    assert history[-1]["train_loss"] < history[0]["train_loss"]
    # hidden-feature columns were zeroed: the bootstrapped head is a pure
    # function of the four observables
    first = graft.nfet.head[0]
    assert float(first.weight[:, :32].detach().abs().sum()) == 0.0
    assert float(first.weight[:, 32:].detach().abs().sum()) > 0.0

    # checkpoint round-trip with the head_trained marker
    out = tmp_path / "ckpt.pt"
    save_controller_checkpoint(graft, out, metrics)
    ckpt = torch.load(out, map_location="cpu", weights_only=False)
    assert ckpt["head_trained"] is True
    fresh = small_graft()
    fresh.load_state_dict(ckpt["graft"])


def test_trained_head_fires_on_clear_events():
    torch.manual_seed(5)
    graft = small_graft()
    sequences = synth_scenarios(200, seq_len=160, seed=4)
    dataset = build_dataset(sequences, d_model=32, seed=4)
    train_control_head(graft, dataset, epochs=25, lr=2e-3, batch_size=64, seed=4)
    head = graft.nfet.head

    def head_label(entropy, drift, gate, regime) -> str:
        features = torch.cat([
            torch.zeros(32),
            torch.tensor([entropy, drift, gate, regime]),
        ]).unsqueeze(0)
        with torch.no_grad():
            return CONTROL_LABELS[int(head(features).argmax(dim=-1))]

    # canonical events from the synthetic distribution
    assert head_label(6.5, 0.05, 0.7, 2.0) == "retrieve"
    assert head_label(1.0, 0.01, 0.7, 2.0) == "finalize"
    assert head_label(3.8, 0.7, 0.7, 2.0) == "verify"
    assert head_label(3.0, 0.05, 0.7, 0.1) == "branch"


def test_drift_override_reaches_controller_state():
    graft = small_graft()
    hidden = torch.randn(2, 1, 32)
    override = torch.tensor([0.42, 0.17])
    out = graft(hidden, base_logits=torch.randn(2, 1, 64), drift_override=override)
    assert torch.allclose(out.nfet_state.hidden_drift, override)
    # without the override, T=1 drift is zero
    out2 = graft(hidden, base_logits=torch.randn(2, 1, 64))
    assert float(out2.nfet_state.hidden_drift.abs().sum()) == 0.0


def test_outcome_examples_relabel_decisions_by_receipt(tmp_path):
    import json
    from lolm.nfet_controller_train import outcome_examples, build_dataset

    def fr(e, d=0.05, g=0.7, r=2.0, step=1):
        return {"logit_entropy": e, "hidden_drift": d, "gate_mean": g,
                "regime_entropy": r, "step": step}

    frames = ([fr(3.0, step=i + 1) for i in range(10)]          # seg1: retrieve, found nothing
              + [fr(3.4, step=i + 11) for i in range(10)]        # seg2: verify -> revise
              + [fr(1.0, step=i + 21) for i in range(10)])       # seg3: finalize
    run = {
        "type": "nfet_agent_run",
        "frames": frames,
        "proof": {"verdict": "nfet_control_visible", "changed_text": True},
        "timeline": [
            {"telemetry_frames": 10,
             "decision": {"label": "retrieve", "source": "heuristic"},
             "action": {"kind": "retrieve", "added": 0}},
            {"telemetry_frames": 10,
             "decision": {"label": "verify", "source": "head"},
             "action": {"kind": "verify", "verdict": "revise"}},
            {"telemetry_frames": 10,
             "decision": {"label": "finalize", "source": "heuristic"},
             "action": {"kind": "finalize"}},
            # budget-forced entries are not policy choices and must be skipped
            {"telemetry_frames": 0,
             "decision": {"label": "continue", "source": "budget"},
             "action": {"kind": "continue"}},
        ],
    }
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps(run) + "\n" + "not json\n")

    rows = outcome_examples(log, sustain=4)
    # 3 policy decisions x sustain-4 tails
    assert len(rows) == 12
    targets = [t for _, t, _ in rows]
    weights = [w for _, _, w in rows]
    # fruitless retrieve relabeled as continue with corrective weight
    assert targets[:4] == [0, 0, 0, 0] and weights[0] == 1.25
    # revise-verify confirmed as verify
    assert targets[4:8] == [2, 2, 2, 2] and weights[4] == 1.5
    # finalize kept, full weight because the answer changed
    assert targets[8:] == [4, 4, 4, 4] and weights[8] == 1.25
    # frames carry the segment telemetry they came from
    assert abs(rows[4][0].logit_entropy - 3.4) < 1e-6

    # rows integrate into a trainable dataset with per-sample weights
    ds = build_dataset([], d_model=32, extra_examples=rows)
    assert ds.features.shape == (12, 36)
    assert ds.weights is not None and float(ds.weights[0]) == 1.25
    assert ds.class_counts[0] == 4 and ds.class_counts[2] == 4 and ds.class_counts[4] == 4


def test_outcome_weighted_training_runs(tmp_path):
    import json
    from lolm.nfet_controller_train import outcome_examples, build_dataset, train_control_head
    from lolm.nfet_graft import LOLMNFETGraft

    def fr(e, step):
        return {"logit_entropy": e, "hidden_drift": 0.05, "gate_mean": 0.7,
                "regime_entropy": 2.0, "step": step}

    runs = []
    for k in range(6):
        frames = [fr(3.0 + 0.1 * k, i + 1) for i in range(12)]
        runs.append(json.dumps({
            "type": "nfet_agent_run", "frames": frames,
            "proof": {"verdict": "nfet_control_visible", "changed_text": True},
            "timeline": [{"telemetry_frames": 12,
                          "decision": {"label": "retrieve", "source": "head"},
                          "action": {"kind": "retrieve", "added": 1 if k % 2 else 0}}],
        }))
    log = tmp_path / "log.jsonl"
    log.write_text("\n".join(runs))
    extras = outcome_examples(log)
    ds = build_dataset(synth_scenarios(20, seq_len=60), d_model=32,
                       extra_examples=extras, seed=1)
    graft = LOLMNFETGraft(d_model=32, n_regimes=8, latent_backend="gru_debug")
    metrics = train_control_head(graft, ds, epochs=2, batch_size=64)
    assert 0.0 <= metrics["val_acc"] <= 1.0
    assert metrics["train_rows"] > 0
