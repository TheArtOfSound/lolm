# ARTEX × LOLM: evidence-backed architecture audit

**Research date:** 2026-11-15  
**Scope:** defensive, static research only; no target scanning; no ARTEX binary executed.  
**Status:** README and selected source files inspected. Static implementation review is partial; dependencies, build behavior, and runtime security have not been verified.

## Primary references (specific and provenance-aware)

| Source | What it supports | Limit |
|---|---|---|
| [ARTEX global fork](https://github.com/jiwoochris/artex-global) | Go/Next.js, Norma SDK, worker/planner, PostgreSQL, dual graph, scope/approval documentation | Maintained derivative; not necessarily byte-identical to deleted upstream |
| [ARTEX English fork](https://github.com/BaaRai/ARTEX) | Alternative public code lineage and change history | Fork behavior may diverge |
| [Microsoft 2026-10-21](https://www.microsoft.com/en-us/security/blog/2026/10/21/storm-0940-uses-artex-agentic-ai-connectwise-supply-chain-compromise/) | Storm-0940 campaign details and sub-three-hour access in some cases | Attacker success not universal; many sign-in attempts failed |
| [Microsoft 2026-11-06](https://www.microsoft.com/en-us/security/blog/2026/11/06/artex-abuse-expands-as-cybercriminals-target-financial-sector/) | AI-enabled attack-chain observations | Detections rely on telemetry and attribution choices |
| [Cloudflare 2026-11-13](https://blog.cloudflare.com/adapting-to-ai-penetration-testing-orchestrators) | Reported growth of AI pentest tool requests and recommendations for defenders | Request volume != successful compromises |
| [FBI FLASH 2026-11-13](https://www.ic3.gov/CSA/2026/261113.pdf) | Official warning about malicious ARTEX use | Indicators and cases evolve; consult source before operational rules |
| [LOLM repository](https://github.com/TheArtOfSound/LOLM) | NFET observe/retrieve/verify/branch/finalize, memory, local model bridge, agent code | Published code claims are not proof of locally loaded checkpoint or successful benchmark |

## Architecture lessons to test, without importing offensive code

1. **Shared state instead of independent agents.** ARTEX documentation describes a shared dual-graph state and planner-visible todo list. Defensive counterpart: compact evidence graph connecting principal, device, event and resource, with immutable provenance IDs and bounded memory.
2. **Observation separated from intent.** The planner/workers divide work. Defensive counterpart: parser validates read-only logs; evaluator scores; monitor may recommend human review. A model never directly authorizes a tool call.
3. **Time and escalation.** Microsoft describes short windows from initial targeting to privileged access. Defensive counterpart: evaluate first-alert time relative to final suspicious event and incident onset, not only terminal accuracy.
4. **Untrusted tool output and prompt injection.** External text is data. The synthetic lab ignores free-form messages when making scoring decisions and rejects unknown schema fields.
5. **Evidence honesty.** LOLM already has receipts and NFET decisions. Defensive counterpart: event IDs, deterministic report hashes, explicit model-loaded status, and no claims of trained-head performance without the checkpoint.

## Selected source-level findings (fork main at inspection time)

These findings are based on direct inspection of the named **source files**, not merely the README. The exact fork commit still needs pinning before reproducible code-to-code comparison.

- [`agent/planner.go`, lines 19–42](https://github.com/jiwoochris/artex-global/blob/main/agent/planner.go#L19-L42): a graph-change-triggered planner is the sole producer of exploration intents; it retains a shared work directory, a compaction reference, and callbacks to terminate or steer work. **Defensive translation:** have one review-policy component own all escalation decisions while separate workers only gather and normalize evidence.
- [`agent/worker.go`, lines 23–27](https://github.com/jiwoochris/artex-global/blob/main/agent/worker.go#L23-L27): each worker claims one intent and reports discovered facts; multiple workers can run concurrently. **Defensive translation:** design bounded, replayable event ingestion workers without model-controlled tools.
- [`agent/coldgraph.go`, lines 1–12](https://github.com/jiwoochris/artex-global/blob/main/agent/coldgraph.go#L1-L12): cold-graph compression is implemented as a DB/LLM-independent graph transformation with explicit upstream/downstream edge semantics. **Defensive translation:** benchmark bounded memory compaction and measure whether evidence is lost before an incident is correlated.
- [`agent/constraints.go`, lines 7–48](https://github.com/jiwoochris/artex-global/blob/main/agent/constraints.go#L7-L48): task scope constraints are included in a high-priority model prompt. A prompt is **not** a reliable authorization boundary. The defensive build does not expose network-capable tools to the model; policy must be enforced in code.
- [`server/intercept.go`, lines 40–69](https://github.com/jiwoochris/artex-global/blob/main/server/intercept.go#L40-L69): unmatched interception requests can be passed to an LLM reviewer. This is a model-backed verdict, distinct from an independent hard-deny policy. No assumption is made about all paths or defaults without further code tracing.
- [`server/engine.go`, lines 102–110](https://github.com/jiwoochris/artex-global/blob/main/server/engine.go#L102-L110): event-driven scheduling activates planner and parallel workers, with the doc explicitly stating that its engine has no built-in simulation mode. Accordingly, running that engine is **not** how this isolated benchmark simulates defensive events.
- [`local_ui/mcp_server.py`, `nfet_monitor_text`](https://github.com/TheArtOfSound/LOLM/blob/main/local_ui/mcp_server.py): LOLM requires a loaded backbone and graft to return token telemetry; otherwise the function returns an error. Its decision includes `decision.label`, provenance, and `head_trained`. The present adapter accepts *only supplied monitor JSON* and deliberately does not fabricate that state.

## Open issues and falsification tests

- **[PARTIAL] Implement full source-file audit.** Selected planner, worker, engine, graph, constraint and reviewer paths have been inspected. Need pinning, complete approval-path tracing, dependency review, runtime tests, and confirmation across forks before architectural parity claims.
- **[OPEN] Confirm license details at pinned revisions.** ARTEX forks identify AGPL-3.0; this new module copies no implementation. Contributor obligations and downstream distribution must be assessed separately.
- **[OPEN] Model baseline fairness.** Current handcrafted data favors sequence-aware correlation. Add a strong industry-style windowed rules baseline, and independent scenario generator, before claims about superiority.
- **[OPEN] Ground-truth uncertainty.** Real security telemetry labels are noisy, sparse and sensitive. Use consented datasets with provenance and deidentification, not leaked personal information.
- **[OPEN] LOLM checkpoint integration.** The `nfet-advisory` parser only reads monitor output. It does not instantiate the model, connect to an endpoint, or measure its decision quality.
- **[OPEN] Security review.** Keep external network disabled in the lab, do not ship a scan/exploit runner, and require a human approval gate for any future live defensive deployment.

## Excluded by design

No exploit chaining, intrusion automation, credentials harvesting, persistence, RAT integration, unauthorized network enumeration, data theft, denial-of-service, or autonomous attack execution. These capabilities do not improve the stated defensive hypothesis test.
