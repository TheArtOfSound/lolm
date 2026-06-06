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
