# Copyright (c) 2026 Qira LLC. All rights reserved.
import random
from pathlib import Path

import pytest
import torch

from lolm.evolve import run_cycle


@pytest.fixture(autouse=True)
def _deterministic_rng():
    """Pin every RNG this module depends on.

    run_cycle seeds its synthetic DATA (synth_scenarios(..., seed=1000 + cyc)) but the
    fresh head in _fresh_graft draws its initial weights from the GLOBAL torch RNG. So
    the size of the first cycle's gain depended on whatever tests ran earlier and left
    the RNG advanced — the promote assertion passed alone and failed intermittently in
    the full suite, which is how CI ended up red for reasons unrelated to the code.
    """
    torch.manual_seed(0)
    random.seed(0)
    try:
        import numpy as np
        np.random.seed(0)
    except ImportError:
        pass
    yield


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
