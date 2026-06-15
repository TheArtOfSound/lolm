# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Tests for the Hugging Face daily ingestion + gated training layers."""

import json

import pytest

from lolm.research.memory import ResearchMemoryStore
from lolm.research import hf_ingest as hi
from lolm.research import hf_train as ht


# ---- a controlled fake HF index covering every filter branch ----------------
def _ds(rid, dl=1000, likes=10, lic="apache-2.0", gated=False, tags=None, card=True):
    return {"id": rid, "downloads": dl, "likes": likes, "gated": gated,
            "tags": tags if tags is not None else ["task_categories:question-answering"],
            "cardData": ({"license": lic} if card else {}),
            "license": lic, "description": rid}


FAKE = {
    "reasoning": [
        _ds("good/reasoning-traces", dl=80000, likes=900, lic="apache-2.0",
            tags=["reasoning", "task_categories:text-generation"]),          # accept + candidate
        _ds("ncorp/reasoning-private", lic="cc-by-nc-4.0",
            tags=["reasoning"]),                                              # noncommercial → memory only
        _ds("mystery/reasoning-x", lic=None, tags=["reasoning"]),            # unknown license → memory only
        _ds("gatedco/reasoning-gated", gated=True, tags=["reasoning"]),      # gated → hard reject
        _ds("toxic/reasoning-nsfw", lic="mit",
            tags=["reasoning", "not-for-all-audiences", "nsfw"]),            # poison → hard reject
        _ds("dupe/reasoning-traces", dl=80000, lic="apache-2.0",
            tags=["reasoning"]),                                             # distinct id, accept
        _ds("noise/cat-photos", lic="mit", tags=["images", "cats"]),        # irrelevant
        _ds("tiny/reasoning-empty", dl=1, likes=0, lic="mit", card=False,
            tags=["reasoning"]),                                            # low quality
    ],
    "tool use": [
        _ds("good/reasoning-traces", dl=80000, lic="apache-2.0",
            tags=["reasoning"]),                                            # duplicate across topics
        _ds("agentco/tool-use-logs", dl=50000, likes=300, lic="mit",
            tags=["tool use", "agent"]),                                    # accept + candidate
    ],
}


def _list_fn(topic, limit):
    return FAKE.get(topic, [])


def test_classify_license():
    assert hi.classify_license("apache-2.0") == "commercial_ok"
    assert hi.classify_license("MIT") == "commercial_ok"
    assert hi.classify_license("cc-by-nc-4.0") == "noncommercial"
    assert hi.classify_license("gpl-3.0") == "copyleft"
    assert hi.classify_license(None) == "unknown"
    assert hi.classify_license("other") == "unknown"
    assert hi.classify_license("some-weird-license") == "custom"


def test_quality_and_poison():
    hi_meta = hi._meta(_ds("x/y", dl=100000, likes=1000, tags=["a", "b"]))
    assert hi.quality_score(hi_meta) > 0.8
    low = hi._meta(_ds("x/z", dl=0, likes=0, card=False, tags=[]))
    assert hi.quality_score(low) < 0.25
    assert hi.poison_flags(hi._meta(_ds("data/x", tags=["nsfw"]))) == ["nsfw"]


def test_ingest_filters_and_receipt(tmp_path):
    store = ResearchMemoryStore(str(tmp_path / "mem.jsonl"))
    queue = hi.TrainingCandidateQueue(tmp_path / "cands.jsonl")
    res = hi.ingest(memory_store=store, queue=queue, list_fn=_list_fn,
                    topics=["reasoning", "tool use"], per_topic=20, now=1_781_740_800)
    r = res.receipt

    # good/reasoning-traces, dupe/reasoning-traces, agentco/tool-use-logs accept.
    assert r["datasets_accepted"] == 3
    assert r["training_examples_queued"] == 3
    assert len(res.candidates_queued) == 3

    rr = r["rejection_reasons"]
    assert rr["gated_or_unapproved"] == 1          # gatedco
    assert rr["poison_flagged"] == 1               # toxic/nsfw
    assert rr["noncommercial"] == 1                # ncorp
    assert rr["unknown_license"] == 1              # mystery
    assert rr["low_quality"] == 1                  # tiny/empty
    assert rr["irrelevant"] == 1                   # cat-photos
    assert rr["duplicate"] >= 1                    # good/reasoning-traces seen twice

    # The hard-rule invariants.
    assert r["adapters_trained"] == 0
    assert r["model_weights_changed"] is False
    assert r["source"] == "huggingface"
    assert r["ingest_date"] == "2026-06-18"

    # noncommercial + unknown still LEARNED (memory), just not training candidates.
    assert r["memories_written"] >= 5
    mems = store.stats()
    assert mems["total"] == r["memories_written"]


def test_candidates_are_queued_not_trained(tmp_path):
    store = ResearchMemoryStore(str(tmp_path / "mem.jsonl"))
    queue = hi.TrainingCandidateQueue(tmp_path / "cands.jsonl")
    hi.ingest(memory_store=store, queue=queue, list_fn=_list_fn,
              topics=["reasoning"], per_topic=20)
    rows = queue.all()
    assert rows and all(c["trained"] is False for c in rows)
    assert all(c["license_class"] == "commercial_ok" for c in rows)
    st = queue.stats()
    assert st["untrained"] == st["total"]


def test_promotion_gate_blocks_weak_improvement():
    gate = ht.PromotionGate(min_improvement=0.02, max_regressions=0)
    d = ht.evaluate_promotion(eval_before=0.70, eval_after=0.705, regressions=0,
                              license_clean=True, gate=gate)
    assert d["promoted"] is False
    assert "improvement" in d["reason"]


def test_promotion_gate_blocks_regression_and_license():
    gate = ht.PromotionGate()
    assert ht.evaluate_promotion(eval_before=0.6, eval_after=0.8, regressions=2,
                                 license_clean=True, gate=gate)["promoted"] is False
    assert ht.evaluate_promotion(eval_before=0.6, eval_after=0.8, regressions=0,
                                 license_clean=False, gate=gate)["promoted"] is False


def test_promotion_gate_allows_clean_win():
    d = ht.evaluate_promotion(eval_before=0.60, eval_after=0.68, regressions=0,
                              license_clean=True)
    assert d["promoted"] is True
    rec = ht.training_receipt(base_model="LOLM-controller-v0.3", method="LoRA",
                              candidate_ids=["c1", "c2"], licenses=["apache-2.0"],
                              eval_before=0.60, eval_after=0.68, regressions=0,
                              decision=d, rollback_version="v0.3")
    assert rec["promoted"] is True
    assert rec["model_weights_changed"] is True


def test_training_pipeline_status_is_gated(tmp_path):
    queue = hi.TrainingCandidateQueue(tmp_path / "cands.jsonl")
    queue.add({"repo_id": "a/b", "topic": "reasoning", "license_class": "commercial_ok"})
    pipe = ht.TrainingPipeline(queue, has_gpu=False)
    st = pipe.status()
    assert st["auto_runs"] is False
    assert st["enabled"] is False                  # no GPU + too few candidates
    assert any("GPU" in b for b in st["blockers"])
    assert st["model_weights_changed_recently"] is False
    plan = pipe.dry_run_plan()
    assert plan["executed"] is False
    assert plan["would_train"] == 1
