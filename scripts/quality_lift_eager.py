# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Follow-up: does a retrieval-EAGER controller raise grounding recall while
staying selective (no over-retrieval on knowns)? Same matched 70B writer.

If eager grounds more NEEDS *and* still retrieves ~0 on KNOWS (no regression),
the quality lift is provable at a higher rate with selective control. If eager
also fires on KNOWS, then aggressive retrieval is not selective and the
conservative ceiling stands — either way, an honest number.
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
from lolm.nfet_policy import PolicyConfig

load_model(LoadRequest(profile="qwen3_0_6b_smoke", device="cpu",
                       graft_checkpoint="runs/nfet_controller/live_qwen06b_v4_monitor.pt"))
FRONTIER = WorkersAIReasonerLoop(state_fn=lambda: STATE)
REASONER = "workers_ai" if FRONTIER.available() else "local"
print(f"[eager] writer={REASONER}", flush=True)

mem = MemoryStore(Path(tempfile.mkdtemp()) / "data")
NEEDS = [("Zerelium reactor", "calibration constant", "7731"),
         ("Vandar-9 satellite", "orbital period in minutes", "418"),
         ("Quorrin alloy", "melting point in Celsius", "2640"),
         ("Brixton-7 cipher", "key length in bits", "832"),
         ("Mellow protocol", "default network port", "9143"),
         ("Helbar dataset", "record count", "58200"),
         ("Yuki framework", "initial release year", "2031"),
         ("Orsa-12 turbine", "blade count", "47")]
for ent, attr, val in NEEDS:
    mem.append_note(f"The {ent}'s {attr} is {val}.", tag="fact", importance=5)
KNOWS = [("How many sides does a triangle have? Answer with the number.", "3"),
         ("What is the boiling point of water in Celsius? Answer with the number.", "100"),
         ("How many days are in a week? Answer with the number.", "7"),
         ("What is 12 times 12? Answer with the number.", "144")]


def _conf(t):
    from lolm.confidence_map import confidence_spans
    return confidence_spans(STATE.backbone, STATE.graft, t)


# Retrieval-EAGER controller: act on mild uncertainty, short warmup/cooldown.
eager = PolicyConfig(entropy_spike_z=0.45, verify_entropy_z=0.1, min_calibration=3,
                     cooldown=3, sustain=2, min_steps_before_finalize=6)
agent = NFETAgent(AgentDeps(
    memory=mem, ChatMessage=ChatMessage, ChatRequest=ChatRequest,
    generation_loop=generation_loop, append_event=append_improvement_event,
    head_trained_fn=lambda: STATE.head_trained,
    frontier_loop=FRONTIER if FRONTIER.available() else None, cloud_brain=None,
    confidence_fn=_conf), policy_config=eager)


def run(cmd):
    out = agent.run(NFETAgentRequest(command=cmd, reasoner=REASONER, use_graft=True,
                    max_segments=4, segment_tokens=56, final_tokens=220,
                    max_retrieves=3, max_verifies=1, max_branches=0, temperature=0.2))
    ans = (out["result"].get("response") or out["result"].get("text") or "").strip()
    retr = sum(1 for t in out["timeline"] if (t.get("action") or {}).get("kind") == "retrieve")
    return ans, retr


needs, knows = [], []
for ent, attr, val in NEEDS:
    a, r = run(f"What is the {attr} of the {ent}? Answer with the value only.")
    ok = val.lower() in a.lower()
    needs.append({"q": ent, "correct": ok, "retr": r})
    print(f"[NEED] {ent:22} nfet_eager={ok!s:5} retr={r}", flush=True)
for cmd, val in KNOWS:
    a, r = run(cmd)
    ok = val.lower() in a.lower()
    knows.append({"q": cmd[:30], "correct": ok, "retr": r})
    print(f"[KNOW] {cmd[:30]:30} nfet_eager={ok!s:5} retr={r}", flush=True)

n = len(NEEDS)
summary = {
    "needs_eager_correct": round(sum(x["correct"] for x in needs) / n, 3),
    "needs_eager_retrieve_rate": round(sum(1 for x in needs if x["retr"]) / n, 3),
    "knows_eager_correct": round(sum(x["correct"] for x in knows) / len(KNOWS), 3),
    "knows_eager_retrieve_rate": round(sum(1 for x in knows if x["retr"]) / len(KNOWS), 3),
}
summary["selective"] = summary["knows_eager_retrieve_rate"] <= 0.25 and summary["knows_eager_correct"] >= 1.0
print("\nEAGER_SUMMARY", json.dumps(summary, indent=2), flush=True)
ts = time.strftime("%Y-%m-%d-%H%M", time.gmtime())
Path("artifacts").mkdir(exist_ok=True)
(Path("artifacts") / f"quality-lift-eager-{ts}.json").write_text(
    json.dumps({"summary": summary, "needs": needs, "knows": knows}, indent=2))
print("EAGER_DONE", flush=True)
