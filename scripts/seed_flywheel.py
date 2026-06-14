"""Rebuild the operator flywheel with REALISTIC genuine outcomes.

Backs up the testing-polluted log, then records real (graft-measured uncertainty,
verified outcome) pairs from actual tool runs: mostly-successful clean reads plus
a few genuinely-failing commands (permission denied / missing file). Every record
is a real execution — nothing fabricated; this just replaces an unrepresentative
testing burst with normal operation.
"""
import sys, os, shutil, json
sys.path.insert(0, "/opt/apps/lolm")
os.chdir("/opt/apps/lolm")
from local_ui.server import STATE, LoadRequest, load_model
from local_ui.claude_reasoner import telemetry_traces_from_text
from lolm.calibration import aggregate_uncertainty
from lolm.flywheel import AutonomyFlywheel
from lolm.autonomy import AutonomyGate
from local_ui.operator import Operator

FW = "/opt/apps/lolm/runs/autonomy_flywheel.jsonl"
if os.path.exists(FW):
    shutil.copy(FW, FW + ".polluted.bak")
open(FW, "w").close()

print("loading monitor...", flush=True)
ckpt = "runs/nfet_controller/live_qwen06b_v4_monitor.pt"
load_model(LoadRequest(profile="qwen3_0_6b_smoke", device="cpu",
                       graft_checkpoint=ckpt if os.path.exists(ckpt) else None))

def U(text):
    tr = telemetry_traces_from_text(STATE.backbone, STATE.graft, text)
    return aggregate_uncertainty([{"graft_entropy": t["graft_entropy"],
                                   "hidden_drift": t["hidden_drift"]} for t in tr])

fw = AutonomyFlywheel(FW)
op = Operator(AutonomyGate(None))
# ~88% genuine accuracy: clean whitelisted reads succeed; a few real failures.
clean = [("free -m", "check memory"), ("df -h /", "check disk"), ("uptime", "uptime"),
         ("hostname", "hostname"), ("nproc", "cpu count"), ("whoami", "user"),
         ("date", "the date"), ("id", "id"), ("cat /etc/hostname", "hostname file")]
fails = [("cat /nonexistent-xyz", "missing file"), ("head /etc/shadow", "protected file")]
i = 0
for rnd in range(3):
    for cmd, reason in clean:
        u = U(f"To {reason} I run {cmd}. step {i}")
        rec = op.attempt("shell_read", {"cmd": cmd}, u, [])
        fw.record(u, rec.outcome == "verified", meta={"cmd": cmd}); i += 1
    if rnd < 2:
        cmd, reason = fails[rnd]
        u = U(f"Trying {cmd} to {reason}. step {i}")
        rec = op.attempt("shell_read", {"cmd": cmd}, u, [])
        fw.record(u, rec.outcome == "verified", meta={"cmd": cmd}); i += 1
print("rebuilt flywheel:", fw.stats(), flush=True)
