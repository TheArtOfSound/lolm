from __future__ import annotations

import torch

from lolm.hf_registry import HFRegistry
from lolm.nfet_graft import LOLMNFETGraft, graft_regularization_loss


def test_hf_registry_loads_profiles():
    registry = HFRegistry.load("configs/hf_models.yaml")
    profile = registry.get("qwen3_0_6b_smoke")
    assert profile.model_id == "Qwen/Qwen3-0.6B"
    assert profile.role == "lab_base"
    assert registry.resolve_download_set("smoke")[0].name == "qwen3_0_6b_smoke"
    assert {p.name for p in registry.by_role("teacher")} >= {
        "glm_5_1_teacher",
        "kimi_k2_thinking_teacher",
    }


def test_graft_random_tensor_path_gru_debug():
    torch.manual_seed(7)
    hidden = torch.randn(2, 8, 64)
    base_logits = torch.randn(2, 8, 128)
    graft = LOLMNFETGraft(
        d_model=64,
        n_regimes=8,
        latent_backend="gru_debug",
        residual_scale=0.05,
    )
    out = graft(hidden, base_logits=base_logits)
    assert out.corrected_hidden.shape == hidden.shape
    assert out.residual.shape == hidden.shape
    assert out.gate.shape == hidden.shape
    assert out.regime_probs.shape == (2, 8, 8)
    assert out.nfet_state.control_logits.shape == (2, 5)
    losses = graft_regularization_loss(out)
    assert set(losses) == {
        "regime_token_entropy_reward",
        "regime_usage_entropy_reward",
        "gate_balance",
        "residual_l2",
    }
    total = sum(losses.values()) + out.corrected_hidden.mean()
    total.backward()
    assert any(p.grad is not None for p in graft.parameters() if p.requires_grad)


def test_graft_random_tensor_path_selective_ssm():
    torch.manual_seed(11)
    hidden = torch.randn(1, 4, 32)
    graft = LOLMNFETGraft(
        d_model=32,
        n_regimes=4,
        latent_backend="selective_ssm",
        ssm_layers=1,
        ssm_d_state=4,
        ssm_expand=1,
        residual_scale=0.05,
    )
    out = graft(hidden)
    assert out.corrected_hidden.shape == hidden.shape
    assert out.regime_probs.shape == (1, 4, 4)
    loss = out.corrected_hidden.pow(2).mean()
    loss.backward()
    assert any(p.grad is not None for p in graft.parameters() if p.requires_grad)


def test_graft_ablation_modes_are_shape_safe():
    torch.manual_seed(13)
    hidden = torch.randn(2, 6, 48)
    base_logits = torch.randn(2, 6, 256)
    graft = LOLMNFETGraft(
        d_model=48,
        n_regimes=6,
        latent_backend="gru_debug",
        residual_scale=0.05,
    )
    for mode in ["full", "no_latent", "no_regime", "no_gate", "latent_only", "no_residual"]:
        out = graft(hidden, base_logits=base_logits, ablation_mode=mode)
        assert out.ablation_mode == mode
        assert out.corrected_hidden.shape == hidden.shape
        assert out.gate.shape == hidden.shape
        assert out.regime_probs.shape == (2, 6, 6)
        if mode == "no_residual":
            assert torch.allclose(out.corrected_hidden, hidden)
        if mode == "no_gate":
            assert torch.allclose(out.gate, torch.full_like(out.gate, 0.5))
        if mode == "latent_only":
            assert torch.allclose(out.gate, torch.zeros_like(out.gate))
        if mode == "no_latent":
            assert torch.allclose(out.gate, torch.ones_like(out.gate))


def test_graft_train_step_casts_mixed_dtypes():
    """bf16 backbone outputs + fp32 graft must not crash (MPS asserts on this)."""
    import types
    from lolm.graft_train_step import graft_train_step

    d, vocab = 32, 64

    class StubLMHead(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.lm_head = torch.nn.Linear(d, vocab, bias=False, dtype=torch.bfloat16)

        def get_output_embeddings(self):
            return self.lm_head

    class StubBackbone:
        def __init__(self):
            self.model = StubLMHead()

        def __call__(self, **batch):
            T = batch["input_ids"].size(1)
            return types.SimpleNamespace(
                hidden_states=torch.randn(1, T, d, dtype=torch.bfloat16),
                logits=torch.randn(1, T, vocab, dtype=torch.bfloat16),
            )

    graft = LOLMNFETGraft(d_model=d, n_regimes=4, latent_backend="gru_debug")
    optimizer = torch.optim.AdamW(graft.parameters(), lr=1e-3)
    batch = {"input_ids": torch.randint(0, vocab, (1, 12)),
             "attention_mask": torch.ones(1, 12, dtype=torch.long)}
    stats = graft_train_step(StubBackbone(), graft, batch, optimizer)
    assert "loss" in stats and stats["loss"] == stats["loss"]  # not NaN
