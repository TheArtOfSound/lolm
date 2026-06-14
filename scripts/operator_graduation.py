import sys, os
sys.path.insert(0, "/opt/apps/lolm")
os.chdir("/opt/apps/lolm")
from local_ui.server import STATE, LoadRequest, load_model
from local_ui.claude_reasoner import telemetry_traces_from_text
from lolm.calibration import aggregate_uncertainty
from lolm.flywheel import AutonomyFlywheel
from lolm.autonomy import AutonomyGate
from local_ui.operator import Operator

ckpt = "runs/nfet_controller/live_qwen06b_v4_monitor.pt"
print("loading monitor...", flush=True)
load_model(LoadRequest(profile="qwen3_0_6b_smoke", device="cpu",
                       graft_checkpoint=ckpt if os.path.exists(ckpt) else None))

def U(text):
    tr = telemetry_traces_from_text(STATE.backbone, STATE.graft, text)
    return aggregate_uncertainty([{"graft_entropy": t["graft_entropy"],
                                   "hidden_drift": t["hidden_drift"]} for t in tr])

demo = "/tmp/demo_flywheel.jsonl"
open(demo, "w").close()
fw = AutonomyFlywheel(demo, min_fit=20)
op = Operator(AutonomyGate(None))  # cold gate: read-tier cold-start runs the reads
cmds = [("free -m", "check memory"), ("df -h /", "check disk"), ("uptime", "check uptime"),
        ("hostname", "get hostname"), ("nproc", "count cpus"), ("whoami", "current user"),
        ("date", "get the date"), ("id", "get id")]
i = 0
while fw.count < 24:
    cmd, reason = cmds[i % len(cmds)]
    u = U(f"To {reason} on this server I will run the command {cmd}. Attempt {i}.")
    rec = op.attempt("shell_read", {"cmd": cmd}, u, [])
    fw.record(u, rec.outcome == "verified", meta={"cmd": cmd})
    i += 1
print("clean demo flywheel:", fw.stats(), flush=True)

cal = fw.calibrator()
cold = AutonomyGate(None)
warm = AutonomyGate(cal)
print("\nGRADUATION — run_python (reversible tier), SAME measured uncertainty:")
print(f"{'U':>5} {'COLD (no record)':>18} {'WARM (earned)':>15} {'P(correct)':>11}")
for u in [0.5, 0.8, 1.0, 1.2]:
    print(f"{u:>5} {cold.decide(u,'reversible').mode:>18} "
          f"{warm.decide(u,'reversible').mode:>15} {warm.p_correct(u)[0]:>11.3f}")

print("\nLIVE run_python through the EARNED gate:")
warm_op = Operator(warm)
u = U("Compute 2 to the power 10 using python and print it.")
rec = warm_op.attempt("run_python", {"code": "print(2**10)"}, u, [])
out = (rec.observation or {}).get("data", {}).get("stdout", "").strip() if rec.executed else "-"
print(f"  U={u} gate={rec.outcome} executed={rec.executed} stdout={out!r}")
