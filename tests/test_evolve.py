# Copyright (c) 2026 Qira LLC. All rights reserved.
from pathlib import Path
from lolm.evolve import run_cycle


def test_evolution_promotes_then_never_regresses(tmp_path):
    root = Path(tmp_path)
    r1 = run_cycle(root, device="cpu", synth_n=60, epochs=3)
    assert r1["cycle"] == 1
    assert r1["weights_changed"] is True            # fresh head → big gain → promoted
    assert r1["val_acc_after"] > r1["val_acc_before"]
    assert (root / "current.pt").exists()           # real checkpoint written
    best = r1["best_val_acc"]
    # several more cycles: best_val_acc must NEVER go down (gate blocks regressions)
    for _ in range(3):
        r = run_cycle(root, device="cpu", synth_n=60, epochs=3)
        assert r["best_val_acc"] >= best - 1e-9
        best = r["best_val_acc"]
        if not r["weights_changed"]:
            assert r["decision"].startswith("rejected")
