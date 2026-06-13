# Copyright (c) 2026 Qira LLC. All rights reserved.
"""QEV seals the FULL run bundle, not a summary (complaint #9)."""

from local_ui.vault_routes import _run_to_payload
from lolm.qev_vault import seal, unseal

FAKE_RUN = {
    "command": "What is 3 x 10 x $55?",
    "reasoner": "workers_ai",
    "result": {"response": "It is $1,650.", "profile": "workers_ai:llama-3.3-70b"},
    "draft": "First compute 30 hours, then 30 x 55.",
    "timeline": [{"segment": 1, "decision": {"label": "verify", "source": "audit"},
                  "action": {"kind": "verify", "verdict": "ok"}}],
    "frames": [{"logit_entropy": 0.5, "step": 1}, {"logit_entropy": 0.4, "step": 2}],
    "evidence": [{"id": "memory:abcd1234", "kind": "memory", "text": "rate is $55/hour"}],
    "retrieval": {"retrieved": 1, "used": 1, "decorative": 0, "items": []},
    "confidence": {"spans": [], "available": True},
    "base": {"response": "around 3 grand"},
    "counters": {"segments": 1},
    "ended_by": "audit_verified",
    "provenance": ["Self-checked the draft"],
    "proof": {"verdict": "control_visible"},
    "receipt": {"verdict": "control_visible", "model_used": "workers_ai:llama-3.3-70b",
                "run_mode": "LIVE_NFET_FRONTIER", "fallback_used": False},
    "controller_config": {"window": 160, "sustain": 4, "cooldown": 16},
}


def test_bundle_carries_raw_traces_not_just_summary():
    p = _run_to_payload(FAKE_RUN)
    # the raw material to reproduce the run must all be present
    for key in ("command", "answer", "model", "controller_config", "evidence",
                "retrieval", "draft", "timeline", "frames", "confidence", "base",
                "bundle_sha256"):
        assert key in p, f"sealed bundle missing raw field: {key}"
    assert p["model"]["used"] == "workers_ai:llama-3.3-70b"
    assert p["model"]["run_mode"] == "LIVE_NFET_FRONTIER"
    assert p["evidence"][0]["text"] == "rate is $55/hour"
    assert p["controller_config"]["window"] == 160


def test_bundle_seals_and_verifies():
    p = _run_to_payload(FAKE_RUN)
    env = seal(p, "correct horse battery staple")
    inner, integrity = unseal(env, "correct horse battery staple")
    assert integrity.get("aead_authenticated") is True
    got = inner["payload"]
    assert got["bundle_sha256"] == p["bundle_sha256"]
    assert got["draft"] == FAKE_RUN["draft"]
    assert got["frames"] == FAKE_RUN["frames"]


def test_bundle_hash_changes_if_trace_tampered():
    p1 = _run_to_payload(FAKE_RUN)
    tampered = dict(FAKE_RUN, draft="a different draft that was never generated")
    p2 = _run_to_payload(tampered)
    assert p1["bundle_sha256"] != p2["bundle_sha256"]
