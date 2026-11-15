# LOLM / NFET defensive security-regime lab (Phase 1)

**Status: executable offline research baseline, not a deployed product.** It does
**not** load a trained LOLM checkpoint or make defensive performance claims about
LOLM. All benchmarks use fictional, deterministic event streams.

## Sources and scope

The FBI's 2026-11-13 ARTEX advisory documents agentic attack automation.
The public jiwoochris/artex-global defensive materials include Sigma detections
for the exact artex-enrich/1.0 User-Agent. We treat this as a
**low-confidence, spoofable clue**, not proof of an intrusion.

- FBI advisory: https://www.ic3.gov/CSA/2026/261113.pdf
- Public detections: https://github.com/jiwoochris/artex-global/tree/main/detections
- Google analysis: https://cloud.google.com/blog/topics/threat-intelligence/artex-and-friends-enter-agentic-offensive-frameworks

No offensive source was incorporated, vendored, or executed. This implementation
contains no exploit runner, scanners, target enumeration, remote execution, or
outbound network client. ARTEX's AGPL-3.0 license is a separate concern if any
of its actual source code is later copied into LOLM.

## Current experiment

The module lolm.security_research.lab accepts strictly typed, chronological
JSONL telemetry; it computes two independent baselines:

1. Event sequence rules (auth failures, privilege changes, exports, UA cue).
2. A decayed, one-sided CUSUM-like actor-level signal-shift heuristic.
3. Hybrid: OR union of the two baselines (not a trained fusion).

The truth label is held exclusively for evaluation; it is never consulted by
detection. Incoming User-Agent and source strings are inert data, not prompts.

Every event generates a SHA-256 hash-chain receipt with input event hash, mode,
decision, and previous hash. This is tamper-evident but NOT signed and does
not prove authenticity of the original log source.

## Commands (Python 3.10+; stdlib only)

    python -m unittest discover -s tests -p test_security_research.py -v
    python -m lolm.security_research.cli benchmark
    python -m lolm.security_research.cli simulate /tmp/lolm-events.jsonl
    python -m lolm.security_research.cli analyze /tmp/lolm-events.jsonl --mode hybrid > /tmp/lolm-run.json
    python -m lolm.security_research.cli verify /tmp/lolm-run.json

Event JSONL example:

    {"ts":1800000000,"actor":"fictional-user","kind":"login_failed","source":"synthetic","user_agent":"","remote":false,"truth":false}

Allowed kinds: login_failed, login_success, privilege_grant, bulk_export,
token_used, http_request, ordinary_action.

## Scientific gates before making claims

- Replace toy fixtures with rights-cleared labeled, temporally split SOC data;
  check deduplication and contamination.
- Report per-incident recall, false alerts per host-day, detection latency,
  analyst cost, inference overhead, and calibration.
- Integrate a frozen actual LOLM checkpoint in observer-only mode; measure
  hidden-state, regime and gate dynamics, not just hand-authored risk scores.
- Compare with matched compute/latency and ablate neural regime, memory
  and NFET control against simple statistical baselines.
- Red-team adversarial log messages and prompt-injection canaries before
  connecting any tool interfaces. No unapproved execution actions.
- Do not treat this toy benchmark as validated real-world cyber detection.

## Limitations

No training, real-world intrusion, live feed, model inference, cloud deployment
or real ARTEX identification has occurred in this phase. The rules can be
spoofed or evaded, and benign high-volume behavior can be misclassified.
The fixed fictional attack schedule makes the synthetic benchmark especially
weak evidence of generalization.
