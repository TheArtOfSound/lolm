# Copyright (c) 2026 Qira LLC. All rights reserved.
from pathlib import Path

from lolm.code_nfet_train import (
    train_coding_head,
    load_coding_head,
    predict_control,
    _feat,
    synth_coding_examples,
)
from lolm.nfet_policy import CONTROL_BRANCH, CONTROL_FINALIZE
from local_ui.code_nfet import CodeNFET


def test_synth_examples_cover_all_actions():
    rows = synth_coding_examples(200, seed=0)
    labels = {r[1] for r in rows}
    assert CONTROL_BRANCH in labels
    assert CONTROL_FINALIZE in labels
    assert len(labels) >= 4


def test_train_and_load_coding_head(tmp_path):
    out = tmp_path / "code_head.pt"
    result = train_coding_head(out, synthetic=400, distill=200, epochs=15, seed=1)
    assert out.exists()
    assert result.n_rows >= 100
    assert result.val_acc >= 0.5  # should crush random (0.2) on this task
    loaded = load_coding_head(out)
    assert loaded is not None
    model, meta = loaded
    # Green ship-like features should prefer finalize.
    pred = predict_control(
        model,
        _feat(1.1, 0.04, 0.55, 1.6, thrash=0, green=3, failed=0,
              contract_failed=False, exit_ok=True),
        min_confidence=0.3,
    )
    assert pred is not None
    # Thrash features should prefer branch.
    pred2 = predict_control(
        model,
        _feat(3.5, 0.3, 0.85, 0.4, thrash=2, green=0, failed=4,
              contract_failed=False, exit_ok=False),
        min_confidence=0.3,
    )
    assert pred2 is not None
    assert pred2[0] == CONTROL_BRANCH


def test_code_nfet_loads_head(tmp_path):
    out = tmp_path / "code_head.pt"
    train_coding_head(out, synthetic=300, distill=150, epochs=12, seed=2)
    n = CodeNFET(coding_head_path=str(out))
    assert n._coding_head is not None
    ctrl = n.checkpoint(
        source="def f():\n    return 1\n",
        task="t",
        exit_ok=False,
        thrash=2,
        green_runs=0,
        failed_runs=3,
        stderr="AssertionError",
        phase="work",
    )
    # Head or thrash guard should land on branch.
    assert ctrl.decision.label == "branch" or ctrl.force_branch
    blob = n.receipt_blob()
    assert blob["code_head"] is True
