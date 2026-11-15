# LOLM × ARTEX: isolated defensive research laboratory

**Status: Phase 1 runnable prototype.** No ARTEX executable, network probes, exploit tools, compromised credentials, malware, or live-target integrations are included. All traffic is fabricated and labeled separately. The LOLM/NFET integration is an **advisory-only adapter**, not an evaluated or connected local model.

## Goals

Determine experimentally whether persistent cross-event correlation and future LOLM NFET monitoring improve detection speed, correctness and false-positive control relative to an isolated-event baseline. This is a methodological starting point, not an ARTEX capability reproduction.

## Run (Python 3.10+, standard library only)

From the LOLM repository root:

```bash
python -m research.artex_defense_lab generate --out out/artex-defense --seed 20261115 --repeats 8
python -m research.artex_defense_lab evaluate --input out/artex-defense --out out/artex-defense
python -m research.artex_defense_lab graph --input out/artex-defense --out out/artex-defense
python -m unittest discover -s research/artex_defense_lab/tests -v
open out/artex-defense/report.html  # macOS; otherwise open in your browser
```

Writes `events.jsonl`, `labels.jsonl`, `results.json`, `report.html`, and optionally `evidence_graph.json`. Graph snapshots use case-scoped hashes in node IDs and preserve event/lineage references. Hashes are NOT anonymization (dictionary attacks remain possible); it does not feed the numerical baselines yet. All outputs are local. `out/` should not be committed. The HTML report is static (no scripts, external assets, or trackers).

## Experimental integrity

- Input logs contain **no attack labels**; labels are loaded only inside the evaluation routine.
- Fixtures contain 6 attack and 7 benign patterns. Two benign patterns intentionally mimic suspicious behavior; a low-signal attack intentionally evades detection.
- Baseline A is a single-event threshold. Baseline B adds a 45-minute per-identity memory window, distinct-stage bonus, and cross-device clue. Both use transparent fixed rules; neither uses LOLM weights.
- Reported outcomes are **synthetic demonstration metrics, not generalizable cybersecurity performance**. The dataset was designed to exercise the stateful method; it cannot establish scientific superiority.
- Deterministic seed and SHA-256 content receipts enable reproducibility. SHA-256 is not a cryptographic signature or independent third-party validation.
- No agent executes observations as instructions. Unknown event keys/types fail validation; untrusted message text cannot affect scores.
- An external LOLM monitor JSON response can be parsed with `nfet-advisory --input local-monitor.json`. It is advisory only; the adapter rejects unknown decisions and never asserts that head training has been verified.

## Required next research milestones

1. **Source audit:** Inspect ARTEX's graph schema, planner state and authorization checks *without running the offensive system*. Record exact versions and lines under `research/artex_defense_lab/ARTEX_LOLM_SOURCE_AUDIT.md`.
2. **Dataset independence:** Separate developer and evaluator, use held-out synthetic generators and real consented/appropriately licensed defensive telemetry. No private/leaked user data or harvested credential material.
3. **True LOLM evaluation:** Feed identical sanitized timelines into the LOLM monitor on a controlled, isolated host, record loaded checkpoint and `head_trained`, preserve raw receipts, and compare against all baselines. If model unavailable: mark unavailable, not simulated success.
4. **Longitudinal tests:** Measure time to first alert, precision/recall, false positive burden, compute usage, regime-drift quality, calibration, and performance by scenario type with confidence intervals.
5. **Bounded intervention:** Review-only suggestions before gated defensive recommendations; no autonomous scanning, exploitation, persistence or exfiltration.

## License/provenance

This module is original research code, inspired by documented defensive concepts in ARTEX and public incident reporting, **not a copy of ARTEX source**. It resides inside LOLM and inherits the containing repository's AGPL-3.0-or-later licensing. See `research/artex_defense_lab/ARTEX_LOLM_SOURCE_AUDIT.md` for independent sources and limitations.
