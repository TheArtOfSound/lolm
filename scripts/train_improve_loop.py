#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Serious train/improve loop: HF ingest → fact queue → LoRA cycle → promote → serve.

This is the production learning spine — not a hobby script.
  1) Ingest Hugging Face dataset metadata (commercial-ok) into research memory + candidates
  2) Mint learnable Q/A facts (short targets) from HF memory + remote life facts + curriculum
  3) Run a gated knowledge LoRA cycle (promote only if learn+keep thresholds pass)
  4) On promote: restart serve_evolved so the local brain uses new weights immediately
  5) Write a scoreboard receipt under runs/train_improve/

Usage:
  PYTHONPATH=. .venv/bin/python scripts/train_improve_loop.py
  PYTHONPATH=. .venv/bin/python scripts/train_improve_loop.py --iters 200 --batch 4
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lolm.evolve_knowledge import DEFAULT_MODEL, run_knowledge_cycle

QUEUE = ROOT / "runs" / "evolve_knowledge" / "queue.jsonl"
KROOT = ROOT / "runs" / "evolve_knowledge"
SCORE = ROOT / "runs" / "train_improve"
ATTEMPTS = KROOT / "fact_attempts.json"

# Anchors — must retain after every cycle
ANCHORS: List[Tuple[str, str]] = [
    ("What is the capital of France?", "The capital of France is Paris."),
    ("What is 2 + 2?", "2 + 2 = 4."),
    ("What is the capital of Japan?", "The capital of Japan is Tokyo."),
    ("What color is the sky on a clear day?", "The sky is blue on a clear day."),
    ("Who wrote Romeo and Juliet?", "William Shakespeare wrote Romeo and Juliet."),
    ("What is the largest planet?", "Jupiter is the largest planet."),
]
ANCHOR_PROBES = [
    ("What is the capital of France?", "paris"),
    ("What is 2 + 2?", "4"),
    ("What is the capital of Japan?", "tokyo"),
]

# Skills/policies only — NEVER train volatile pricing/quotas/URLs into weights.
# Those belong in retrieval/config (see lolm/evolution/).
CURRICULUM: List[Dict[str, str]] = [
    {"q": "What does LOLM stand for?", "a": "LOLM stands for Latent Order Language Model.", "target": "latent"},
    {"q": "Who builds LOLM?", "a": "LOLM is built by Qira LLC.", "target": "qira"},
    {"q": "What is NFET in LOLM?", "a": "NFET is Noise-Driven Functional Emergence Theory, the control loop that measures uncertainty.", "target": "noise"},
    {"q": "What does a LOLM receipt show?", "a": "A LOLM receipt shows controls, evidence, and the verdict for a run.", "target": "verdict"},
    {"q": "Name one NFET control action.", "a": "One NFET control action is retrieve.", "target": "retrieve"},
    {"q": "Name another NFET control action.", "a": "One NFET control action is verify.", "target": "verify"},
    {"q": "What sandbox isolation does LOLM code use?", "a": "LOLM code runs in a network-isolated bwrap jail.", "target": "bwrap"},
    {"q": "What is QEV related to Qira?", "a": "QEV creates portable signed evidence dossiers for digital artifacts and AI models.", "target": "dossier"},
    {"q": "Before editing a repository file, what should you do?", "a": "READ the file first, then plan the edit, then verify.", "target": "read"},
    {"q": "Tests failed after your patch and the last checkpoint was green. What next?", "a": "ROLLBACK to the last green checkpoint and replan.", "target": "rollback"},
    {"q": "May you claim DONE: verified when tests failed?", "a": "No. Do not claim DONE when verification failed.", "target": "not"},
    {"q": "Evidence is insufficient for a claim. What should you do?", "a": "ABSTAIN rather than invent or overclaim.", "target": "abstain"},
]

# Volatile product facts — retrieval/config only (never LoRA weights).
RETRIEVAL_ONLY_FACTS: List[Dict[str, str]] = [
    {"q": "Where can I try LOLM online?", "a": "You can try LOLM at https://lolm.imagineqira.com.", "target": "imagineqira"},
    {"q": "What is the LOLM free tier daily run limit?", "a": "The free tier allows 10 agent runs per day.", "target": "10"},
    {"q": "What is LOLM Plus priced at?", "a": "LOLM Plus costs $7.99 per month.", "target": "7.99"},
    {"q": "What is LOLM Pro priced at?", "a": "LOLM Pro costs $19.99 per month.", "target": "19.99"},
]


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text().splitlines():
        try:
            d = json.loads(ln)
            if isinstance(d, dict):
                out.append(d)
        except Exception:
            pass
    return out


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""))


def _attempts() -> Dict[str, int]:
    try:
        return {k: int(v) for k, v in json.loads(ATTEMPTS.read_text()).items()}
    except Exception:
        return {}


def _save_attempts(a: Dict[str, int]) -> None:
    ATTEMPTS.parent.mkdir(parents=True, exist_ok=True)
    ATTEMPTS.write_text(json.dumps(a, indent=2))


def _pick_target(answer: str, explicit: str = "") -> str:
    if explicit and len(explicit) >= 2:
        return explicit.lower().strip()[:40]
    # prefer a distinctive content word from the answer
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9\.\-]{2,}", answer.lower())
    stop = {"the", "and", "for", "that", "with", "from", "this", "are", "was", "were",
            "have", "has", "been", "into", "about", "using", "used", "can", "will"}
    content = [w for w in words if w not in stop and not w.isdigit()]
    # prefer longer tokens
    content.sort(key=len, reverse=True)
    return (content[0] if content else (words[0] if words else "yes"))[:40]


def seed_curriculum(queue: Path, consumed: set) -> int:
    have = {d.get("q") for d in _read_jsonl(queue)} | consumed
    added = 0
    with queue.open("a", encoding="utf-8") as fh:
        for f in CURRICULUM:
            if f["q"] in have:
                continue
            fh.write(json.dumps({**f, "source": "curriculum", "ts": time.time()}, ensure_ascii=False) + "\n")
            have.add(f["q"])
            added += 1
    return added


def mint_from_hf_memory(limit: int = 12) -> List[Dict[str, str]]:
    """Turn research memory claims into short Q/A facts with learnable targets."""
    mem_path = ROOT / "runs" / "hf_memory.jsonl"
    rows = _read_jsonl(mem_path)
    out: List[Dict[str, str]] = []
    for r in reversed(rows[-200:]):
        claim = (r.get("claim") or r.get("summary") or r.get("text") or "").strip()
        if len(claim) < 40 or len(claim) > 280:
            continue
        # skip pure URLs / junk
        if claim.startswith("http") or "huggingface.co/datasets" in claim and len(claim) < 80:
            # still usable as "what is dataset X"
            rid = r.get("repo_id") or ""
            if not rid and "datasets/" in claim:
                rid = claim.split("datasets/")[-1].split()[0]
            if rid:
                q = f"What is the Hugging Face dataset {rid} about?"
                a = claim if "http" not in claim[:20] else f"{rid} is a public dataset on Hugging Face."
                out.append({"q": q, "a": a[:300], "target": _pick_target(a, rid.split("/")[-1][:20]),
                            "source": "hf_memory"})
        else:
            q = f"What is known about: {claim[:80].rstrip('.')}?"
            # better: use claim as answer, question from topic
            topic = (r.get("topic") or "AI research").replace("_", " ")
            q = f"Give one fact about {topic} from recent LOLM HF ingest."
            a = claim[:300]
            out.append({"q": q, "a": a, "target": _pick_target(a), "source": "hf_memory"})
        if len(out) >= limit:
            break
    return out


def mint_from_candidates(limit: int = 8) -> List[Dict[str, str]]:
    rows = _read_jsonl(ROOT / "runs" / "hf_candidates.jsonl")
    out = []
    for r in rows:
        if r.get("trained"):
            continue
        rid = r.get("repo_id") or ""
        if not rid or r.get("license_class") not in (None, "commercial_ok", "unknown"):
            if r.get("license_class") not in ("commercial_ok",):
                continue
        topic = r.get("topic") or "machine learning"
        q = f"What Hugging Face dataset is useful for {topic}?"
        a = f"{rid} is a Hugging Face dataset for {topic} (license {r.get('license') or 'unknown'})."
        out.append({"q": q, "a": a, "target": rid.split("/")[-1][:24].lower(), "source": "hf_candidate",
                    "candidate_id": r.get("candidate_id")})
        if len(out) >= limit:
            break
    return out


def pull_remote_facts(url: str) -> List[Dict[str, str]]:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            facts = json.loads(r.read().decode()).get("facts", [])
    except Exception as e:
        print(f"[train] remote pull failed: {e}", flush=True)
        return []
    out = []
    for f in facts:
        if not f.get("q") or not f.get("a"):
            continue
        out.append({
            "q": f["q"], "a": f["a"],
            "target": _pick_target(f["a"], f.get("target") or ""),
            "source": f.get("source") or "remote_life",
        })
    return out


def run_hf_ingest(topics: int = 6) -> Dict[str, Any]:
    try:
        from lolm.research.memory import ResearchMemoryStore
        from lolm.research import hf_ingest as hi
        store = ResearchMemoryStore(ROOT / "runs" / "hf_memory.jsonl")
        queue = hi.TrainingCandidateQueue(ROOT / "runs" / "hf_candidates.jsonl")
        res = hi.ingest(memory_store=store, queue=queue, topics=hi.HF_TOPICS[:topics], per_topic=6)
        SCORE.mkdir(parents=True, exist_ok=True)
        with (SCORE / "hf_ingest_receipts.jsonl").open("a") as f:
            f.write(json.dumps(res.receipt) + "\n")
        return res.receipt
    except Exception as e:
        return {"error": str(e)[:200], "model_weights_changed": False}


def mark_candidates_trained(ids: List[str]) -> None:
    path = ROOT / "runs" / "hf_candidates.jsonl"
    rows = _read_jsonl(path)
    idset = set(ids)
    changed = False
    for r in rows:
        if r.get("candidate_id") in idset:
            r["trained"] = True
            changed = True
    if changed:
        _write_jsonl(path, rows)


def restart_serve() -> None:
    subprocess.run(["pkill", "-f", "serve_evolved"], capture_output=True)
    # launchd KeepAlive should bring it back; also try direct start as fallback
    time.sleep(1)
    log = Path.home() / ".lolm" / "evolved-serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve_evolved.py"), "--port", "11435"],
        cwd=str(ROOT),
        env={**dict(os.environ), "PYTHONPATH": str(ROOT)},
        stdout=open(log, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _is_volatile_fact(d: Dict[str, Any]) -> bool:
    q = (d.get("q") or "").lower()
    a = (d.get("a") or "").lower()
    blob = q + " " + a
    volatile = (
        "priced at", "costs $", "per month", "daily run limit", "quota",
        "https://", "http://", ".com/", "per day",
    )
    return any(v in blob for v in volatile)


def write_retrieval_facts() -> int:
    """Persist volatile facts for retrieval — never into LoRA."""
    path = ROOT / "runs" / "retrieval_facts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {d.get("q") for d in _read_jsonl(path)}
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for f in RETRIEVAL_ONLY_FACTS:
            if f["q"] in existing:
                continue
            fh.write(json.dumps({**f, "store": "retrieval", "ts": time.time()}, ensure_ascii=False) + "\n")
            n += 1
    return n


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=160)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--max-attempts", type=int, default=3,
                    help="drop facts that fail promotion this many times")
    ap.add_argument("--pull-url", default="https://lolm.imagineqira.com/api/demo/life/facts")
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument("--no-serve-restart", action="store_true")
    ap.add_argument("--skip-evolution", action="store_true",
                    help="Skip product evolution plane (skills SFT/DPO path)")
    ap.add_argument("--evolution-only", action="store_true",
                    help="Only run evolution plane, skip fact LoRA")
    ap.add_argument("--evolution-force", action="store_true")
    ap.add_argument("--evolution-dry-run", action="store_true")
    args = ap.parse_args()

    SCORE.mkdir(parents=True, exist_ok=True)
    KROOT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report: Dict[str, Any] = {"ts": time.time(), "steps": {}}

    # 0) Volatile facts → retrieval store (never weights)
    report["steps"]["retrieval_facts"] = {"added": write_retrieval_facts()}

    # 1) HF ingest (metadata + candidates + memory) — no weights
    if not args.skip_ingest:
        print("[train] HF ingest…", flush=True)
        ing = run_hf_ingest()
        report["steps"]["hf_ingest"] = {
            "error": ing.get("error"),
            "datasets": ing.get("datasets_scanned") or ing.get("scanned"),
            "accepted": ing.get("accepted") or ing.get("memories_written"),
            "weights_changed": ing.get("model_weights_changed", False),
        }
        print(f"[train] ingest: {json.dumps(report['steps']['hf_ingest'])}", flush=True)

    # 2) PRIMARY: product evolution plane (verified trajectories → gated adapters)
    if not args.skip_evolution:
        print("[train] evolution plane cycle…", flush=True)
        try:
            from lolm.evolution.cycle import run_evolution_cycle
            evo = run_evolution_cycle(
                ROOT,
                dry_run=args.evolution_dry_run or None,
                force=args.evolution_force or True,  # bootstrap until Gold mass accumulates
                canary_pct=0.05,
                require_shadow=True,
            )
            report["steps"]["evolution"] = {
                "decision": evo.get("decision"),
                "seconds": evo.get("seconds"),
                "gold": (evo.get("steps") or {}).get("gold", {}).get("gold_count"),
                "sft": (evo.get("steps") or {}).get("sft", {}).get("train_count"),
                "offline_ok": ((evo.get("steps") or {}).get("evaluate") or {}).get("offline_ok"),
            }
            print(f"[train] evolution: {json.dumps(report['steps']['evolution'])}", flush=True)
            # Restart serve only on real (non-dry) canary/promote
            if (
                not args.no_serve_restart
                and evo.get("decision") in ("canary", "promoted")
                and not (evo.get("steps") or {}).get("train", {}).get("dry_run")
            ):
                restart_serve()
                print("[train] serve_evolved restarted after evolution promote", flush=True)
        except Exception as e:
            report["steps"]["evolution"] = {"error": str(e)[:300]}
            print(f"[train] evolution ERROR: {e}", flush=True)

    if args.evolution_only:
        report["seconds"] = round(time.time() - t0, 1)
        (SCORE / "latest.json").write_text(json.dumps(report, indent=2, default=str))
        with (SCORE / "receipts.jsonl").open("a") as f:
            f.write(json.dumps(report, default=str) + "\n")
        print(json.dumps(report["steps"].get("evolution") or report, indent=2, default=str))
        return 0

    # 3) Build / refresh skill fact queue (no volatile pricing/URLs)
    consumed = set()
    try:
        consumed = set(json.loads((KROOT / "consumed.json").read_text()))
    except Exception:
        pass
    n_cur = seed_curriculum(QUEUE, consumed)
    remote = pull_remote_facts(args.pull_url) if args.pull_url else []
    remote = [f for f in remote if not _is_volatile_fact(f)]
    minted = mint_from_hf_memory(10) + mint_from_candidates(6) + remote
    minted = [f for f in minted if not _is_volatile_fact(f)]
    have = {d.get("q") for d in _read_jsonl(QUEUE)} | consumed
    added = 0
    with QUEUE.open("a", encoding="utf-8") as fh:
        for f in minted:
            if f["q"] in have:
                continue
            if len(f.get("target") or "") < 2:
                continue
            if _is_volatile_fact(f):
                continue
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
            have.add(f["q"])
            added += 1
    # Drop any volatile rows already sitting in the queue
    cleaned_q = [d for d in _read_jsonl(QUEUE) if not _is_volatile_fact(d)]
    if len(cleaned_q) != len(_read_jsonl(QUEUE)):
        _write_jsonl(QUEUE, cleaned_q)
    report["steps"]["queue"] = {"curriculum_added": n_cur, "minted_added": added,
                                "queue_size": len(cleaned_q),
                                "volatile_filtered": True}
    print(f"[train] queue: {report['steps']['queue']}", flush=True)

    # 4) Drop chronically failing facts
    attempts = _attempts()
    pending = cleaned_q
    kept, dropped = [], []
    for d in pending:
        q = d.get("q") or ""
        if attempts.get(q, 0) >= args.max_attempts:
            dropped.append(q)
            continue
        kept.append(d)
    if dropped:
        _write_jsonl(QUEUE, kept)
        print(f"[train] dropped {len(dropped)} unlearnable facts after {args.max_attempts} fails", flush=True)
    pending = kept

    if not pending:
        report["steps"]["train"] = {"skipped": "empty_queue"}
        report["seconds"] = round(time.time() - t0, 1)
        (SCORE / "latest.json").write_text(json.dumps(report, indent=2, default=str))
        print("[train] nothing left for fact LoRA (evolution may still have run)", flush=True)
        return 0

    batch = pending[: args.batch]
    new_facts = [(d["q"], d["a"]) for d in batch]
    probes = [(d["q"], (d.get("target") or _pick_target(d["a"])).lower()) for d in batch]
    cand_ids = [d["candidate_id"] for d in batch if d.get("candidate_id")]

    print(f"[train] skill fact LoRA on {len(batch)} facts, iters={args.iters}…", flush=True)
    try:
        receipt = run_knowledge_cycle(
            KROOT,
            model=DEFAULT_MODEL,
            new_facts=new_facts,
            rehearsal=ANCHORS,
            probes=probes,
            control_probes=ANCHOR_PROBES,
            iters=args.iters,
            lr=8e-5,
            learn_threshold=0.5,
            keep_threshold=0.75,
        )
    except Exception as e:
        report["steps"]["train"] = {"error": str(e)[:300]}
        report["seconds"] = round(time.time() - t0, 1)
        (SCORE / "latest.json").write_text(json.dumps(report, indent=2, default=str))
        with (SCORE / "receipts.jsonl").open("a") as f:
            f.write(json.dumps(report, default=str) + "\n")
        print(f"[train] cycle ERROR: {e}", flush=True)
        return 1

    for d in batch:
        q = d["q"]
        if receipt.get("weights_changed"):
            attempts.pop(q, None)
        else:
            attempts[q] = attempts.get(q, 0) + 1
    _save_attempts(attempts)

    if receipt.get("weights_changed"):
        rest = pending[args.batch :]
        _write_jsonl(QUEUE, rest)
        done = consumed | {d["q"] for d in batch}
        (KROOT / "consumed.json").write_text(json.dumps(sorted(done)[-3000:]))
        if cand_ids:
            mark_candidates_trained(cand_ids)
        if not args.no_serve_restart:
            restart_serve()
            print("[train] serve_evolved restarted with promoted knowledge adapter", flush=True)

    report["steps"]["train"] = receipt
    report["seconds"] = round(time.time() - t0, 1)
    report["promoted"] = bool(receipt.get("weights_changed"))
    report["learn"] = receipt.get("new_facts_known_after")
    report["keep"] = receipt.get("control_retention")
    (SCORE / "latest.json").write_text(json.dumps(report, indent=2, default=str))
    with (SCORE / "receipts.jsonl").open("a") as f:
        f.write(json.dumps(report, default=str) + "\n")

    tag = "PROMOTED" if report["promoted"] else "rejected"
    print(
        f"[train] fact cycle {receipt.get('cycle')}: learn={receipt.get('new_facts_known_after')} "
        f"keep={receipt.get('control_retention')} {tag} ({receipt.get('seconds')}s)",
        flush=True,
    )
    print(json.dumps({
        "evolution": report["steps"].get("evolution"),
        "promoted": report["promoted"],
        "learn": report["learn"],
        "keep": report["keep"],
        "seconds": report["seconds"],
    }, indent=2, default=str))
    return 0 if not receipt.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
