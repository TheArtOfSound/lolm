# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Retrieval transparency (#5): prove a note was used, not just present."""

from lolm.retrieval_report import retrieval_support, evidence_id
from lolm.run_receipt import build_receipt


def test_used_note_is_bound_to_supporting_sentence():
    evidence = [{"kind": "memory", "text": "The Eiffel Tower is 330 meters tall in Paris."}]
    answer = "Paris is lovely. The Eiffel Tower stands 330 meters tall."
    rep = retrieval_support(evidence, answer)
    assert rep["retrieved"] == 1 and rep["used"] == 1 and rep["decorative"] == 0
    item = rep["items"][0]
    assert item["used"] is True
    assert item["supported_sentences"]
    assert "330" in " ".join(str(s["shared"]) for s in item["supported_sentences"]) or \
           any("eiffel" in s["snippet"].lower() for s in item["supported_sentences"])


def test_decorative_note_is_flagged_unused():
    evidence = [{"kind": "cloud", "text": "TPU v4 pods are 43 percent faster for training."}]
    answer = "The bat costs $1.00 and the ball costs $0.05."
    rep = retrieval_support(evidence, answer)
    assert rep["used"] == 0 and rep["decorative"] == 1
    assert rep["items"][0]["used"] is False


def test_mixed_used_and_decorative():
    evidence = [
        {"kind": "memory", "text": "Photosynthesis converts sunlight into chemical energy in plants."},
        {"kind": "memory", "text": "The capital of Mongolia is Ulaanbaatar."},
    ]
    answer = "Photosynthesis lets plants convert sunlight into chemical energy."
    rep = retrieval_support(evidence, answer)
    assert rep["retrieved"] == 2 and rep["used"] == 1 and rep["decorative"] == 1


def test_evidence_id_is_stable():
    row = {"kind": "memory", "text": "same text"}
    assert evidence_id(row, 0) == evidence_id(row, 5)  # stable on content, not index
    assert evidence_id(row, 0).startswith("memory:")


def test_receipt_surfaces_retrieval_layer():
    evidence = [{"kind": "memory", "text": "Mercury is the closest planet to the Sun."}]
    answer = "Mercury is the closest planet to the Sun."
    rep = retrieval_support(evidence, answer)
    r = build_receipt("Which planet is closest to the Sun?", answer, [], "nfet_finalize",
                      retrieval=rep)
    layer = r["layers"]["retrieval"]
    assert layer["verdict"] == "retrieval_used" and layer["used"] == 1


def test_receipt_flags_decorative_retrieval():
    evidence = [{"kind": "cloud", "text": "Unrelated note about quantum widgets."}]
    answer = "The sky is blue due to Rayleigh scattering."
    rep = retrieval_support(evidence, answer)
    r = build_receipt("Why is the sky blue?", answer, [], "nfet_finalize", retrieval=rep)
    assert r["layers"]["retrieval"]["verdict"] == "retrieval_decorative"
