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
