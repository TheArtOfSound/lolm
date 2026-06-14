# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Controlled experiment — does NFET control produce a BETTER answer vs baseline?

The honest gap in the contribution matrix: control fires and is consumed, the
graft changes tokens, the telemetry is real — but "quality vs baseline" was never
proven. This isolates the one place control should causally improve a CHECKABLE
outcome: uncertainty-gated retrieval grounding.

Design (matched): SAME writer, SAME prompts, SAME settings. The only variable is
whether the NFET controller may retrieve seeded memory.
  - NEEDS prompts: ask for a fact only present in seeded memory (the writer cannot
    know it). Baseline (no retrieve) must miss/hallucinate; NFET (control retrieves)
    can ground. Score = does the final answer contain the exact seeded value.
  - KNOWS prompts: common facts the writer already knows. Selectivity check —
    NFET must NOT do worse than baseline (it shouldn't inject noise it doesn't need).

If NEEDS(nfet) >> NEEDS(baseline) and KNOWS(nfet) >= KNOWS(baseline), the control
loop causally improves answer correctness under matched conditions — a real,
deterministic, attributable quality lift. If not, we report the null honestly.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/Users/bry/Documents/CLI/lolm")
os.chdir("/Users/bry/Documents/CLI/lolm")

from local_ui.server import (STATE, ChatMessage, ChatRequest, LoadRequest,
                             append_improvement_event, generation_loop, load_model)
from local_ui.memory_store import MemoryStore
from local_ui.nfet_agent import AgentDeps, NFETAgent, NFETAgentRequest
from local_ui.workers_ai_reasoner import WorkersAIReasonerLoop

load_model(LoadRequest(profile="qwen3_0_6b_smoke", device="cpu",
                       graft_checkpoint="runs/nfet_controller/live_qwen06b_v4_monitor.pt"))
FRONTIER = WorkersAIReasonerLoop(state_fn=lambda: STATE)
USE_70B = FRONTIER.available()
REASONER = "workers_ai" if USE_70B else "local"
print(f"[exp] writer = {REASONER} (70B available: {USE_70B})", flush=True)

mem = MemoryStore(Path(tempfile.mkdtemp()) / "data")
NEEDS = [
    ("Zerelium reactor", "calibration constant", "7731"),
    ("Vandar-9 satellite", "orbital period in minutes", "418"),
    ("Quorrin alloy", "melting point in Celsius", "2640"),
    ("Brixton-7 cipher", "key length in bits", "832"),
    ("Mellow protocol", "default network port", "9143"),
    ("Helbar dataset", "record count", "58200"),
    ("Yuki framework", "initial release year", "2031"),
    ("Orsa-12 turbine", "blade count", "47"),
]
for ent, attr, val in NEEDS:
    mem.append_note(f"The {ent}'s {attr} is {val}.", tag="fact", importance=5)

KNOWS = [
    ("How many sides does a triangle have? Answer with the number.", "3"),
    ("What is the boiling point of water in Celsius? Answer with the number.", "100"),
    ("How many days are in a week? Answer with the number.", "7"),
    ("What is 12 times 12? Answer with the number.", "144"),
]


def _conf(t):
    from lolm.confidence_map import confidence_spans
    return confidence_spans(STATE.backbone, STATE.graft, t)


agent = NFETAgent(AgentDeps(
    memory=mem, ChatMessage=ChatMessage, ChatRequest=ChatRequest,
    generation_loop=generation_loop, append_event=append_improvement_event,
    head_trained_fn=lambda: STATE.head_trained,
    frontier_loop=FRONTIER if USE_70B else None, cloud_brain=None, confidence_fn=_conf))


def run(cmd, retrieves):
    out = agent.run(NFETAgentRequest(
        command=cmd, reasoner=REASONER, use_graft=True, max_segments=3,
        segment_tokens=64, final_tokens=220, max_retrieves=retrieves,
        max_verifies=1, max_branches=0, temperature=0.2))
    ans = (out["result"].get("response") or out["result"].get("text") or "").strip()
    retr = sum(1 for t in out["timeline"] if (t.get("action") or {}).get("kind") == "retrieve")
    return ans, retr


def score(ans, val):
    return val.lower() in (ans or "").lower()


results = {"reasoner": REASONER, "needs": [], "knows": []}
for ent, attr, val in NEEDS:
    cmd = f"What is the {attr} of the {ent}? Answer with the value only."
    b_ans, _ = run(cmd, 0)            # baseline: control may NOT retrieve
    n_ans, n_retr = run(cmd, 3)       # nfet: control may retrieve
    row = {"q": ent, "val": val, "baseline_pass": score(b_ans, val),
           "nfet_pass": score(n_ans, val), "nfet_retrieved": n_retr,
           "baseline_ans": b_ans[:140], "nfet_ans": n_ans[:140]}
    results["needs"].append(row)
    print(f"[NEED] {ent:22} baseline={row['baseline_pass']!s:5} nfet={row['nfet_pass']!s:5} retr={n_retr}", flush=True)

for cmd, val in KNOWS:
    b_ans, _ = run(cmd, 0)
    n_ans, n_retr = run(cmd, 3)
    row = {"q": cmd[:44], "val": val, "baseline_pass": score(b_ans, val),
           "nfet_pass": score(n_ans, val), "nfet_retrieved": n_retr}
    results["knows"].append(row)
    print(f"[KNOW] {cmd[:30]:30} baseline={row['baseline_pass']!s:5} nfet={row['nfet_pass']!s:5} retr={n_retr}", flush=True)


def rate(rows, k):
    return round(sum(1 for r in rows if r[k]) / len(rows), 3) if rows else None


summary = {
    "reasoner": REASONER,
    "needs_n": len(NEEDS), "knows_n": len(KNOWS),
    "needs_baseline_correct": rate(results["needs"], "baseline_pass"),
    "needs_nfet_correct": rate(results["needs"], "nfet_pass"),
    "needs_nfet_retrieve_rate": round(sum(1 for r in results["needs"] if r["nfet_retrieved"]) / len(NEEDS), 3),
    "knows_baseline_correct": rate(results["knows"], "baseline_pass"),
    "knows_nfet_correct": rate(results["knows"], "nfet_pass"),
}
summary["needs_lift"] = round((summary["needs_nfet_correct"] or 0) - (summary["needs_baseline_correct"] or 0), 3)
summary["knows_regression"] = round((summary["knows_nfet_correct"] or 0) - (summary["knows_baseline_correct"] or 0), 3)
summary["verdict"] = ("PROVEN: NFET control improves correctness via gated retrieval"
                      if summary["needs_lift"] >= 0.4 and summary["knows_regression"] >= -0.001
                      else "NOT PROVEN / partial — see detail")

print("\nSUMMARY", json.dumps(summary, indent=2), flush=True)
ts = time.strftime("%Y-%m-%d-%H%M", time.gmtime())
outdir = Path("artifacts") / f"quality-lift-{ts}"
outdir.mkdir(parents=True, exist_ok=True)
(outdir / "results.json").write_text(json.dumps({"summary": summary, "detail": results}, indent=2))
print("ARTIFACT", outdir / "results.json", flush=True)
