# Phase 3 — LOLM/NFET Security Research: Falsification Controls

## Outcome (2026-11-15)

This continuation adds an **offline, read-only, scenario-aware falsification harness**.
All events are fictional. No trained LOLM checkpoint was executed, no remote
systems were accessed, and no real incident detection is claimed.

### Method

- Fit robust scores and the threshold only on a separately asserted known-benign
  reference stream (first half reference fitting, second half calibration).
- Keep that same calibration fixed for correctly aligned and event-shuffled
  test traces. Shuffle entire token blocks, preserving within-event ordering.
  Shuffles ask whether event-to-trace *alignment* actually matters.
- For scenario-level analysis, use incident hit rate minus benign-case alert
  rate. With 3 positive and 5 benign fictional scenarios, enumerate all
  56 combinations of 3 positive labels across 8 observed scenario hits.
  This is an **exploratory descriptive permutation statistic**; scenario-label
  exchangeability is unverified. It is NOT proof of statistical significance
  on independent real-world incidents.
- Validate that scenario ranges cover every event exactly once, labels agree
  and scenario IDs are unique. Do not treat 109 event rows as 109 independent
  incidents.

### Reproduce

    python -m unittest discover -s tests -p 'test_security_*.py' -v
    python -m lolm.security_research.cli make-study /tmp/lolm-study

The study generator writes a separately stored \`scenario-labels.json\` file
not included in prompts. The unit suite executes the \`falsify\` CLI end-to-end
using **artificial, uninformative telemetry**, not neural inference.

### Negative control results (synthetic null only)

| Outcome | Value |
|---|---:|
| Held-out fictional events | 109 |
| Labeled suspicious events | 25 |
| True detections | 0 |
| False positive alerts | 0 |
| Incident recall | 0/3 |
| Exact scenario permutations | 56 |
| Exploratory one-sided p-value | 1.0 |
| Shuffled controls at least as discriminative | 7/7 |

This demonstrates that the harness reports *no model improvement* when the
telemetry is uninformative. It says nothing about a trained LOLM model.

### Actual checkpoint-generated evaluation command

After independently verifying a trusted local trained graft checkpoint and
capturing **both** disjoint datasets using the same model:

    python -m lolm.security_research.cli falsify \
      --train-events runs/security_lab/reference_capture/events.jsonl \
      --train-trace runs/security_lab/reference_capture/trace.jsonl \
      --train-manifest runs/security_lab/reference_capture/manifest.json \
      --test-events runs/security_lab/heldout_capture/events.jsonl \
      --test-trace runs/security_lab/heldout_capture/trace.jsonl \
      --test-manifest runs/security_lab/heldout_capture/manifest.json \
      --scenarios runs/security_lab/study_001/scenario-labels.json \
      --ack-known-benign \
      --checkpoint /trusted/path/graft.pt \
      --expected-checkpoint <trusted-independent-sha256>

The model prompt never includes evaluation truth, actor names, scenario labels
or arbitrary untrusted free text. A matching hash checks trace/event content
against the manifest; it does NOT cryptographically attest the inference
process.

## Claim gate

A credible positive result requires an actually trained frozen graft, a
rights-cleared corpus of independent real incidents, incident-level splitting,
matched non-neural baselines, credible telemetry provenance, compute/latency
comparisons and successful negative controls. These conditions are not met.


## Native LOLM-304M research path

The public model card for [Bryan237l/LOLM-304M](https://huggingface.co/Bryan237l/LOLM-304M)
describes the original 304M base-model checkpoint and a local `ckpt_26000.pt`
loader. This file was **not downloaded or inspected** in this work session.

The repository's native `LOLMOutput` exposes `logits`, `h`,
`gate_values` and `regime_probs`. A separate,
strictly fictional-event adapter now extracts these via
`lolm/security_research/native_capture.py`.
**Native hidden drift** is surface-h lag-one MSE, not the Qwen graft's
corrected-hidden drift; treat these as distinct feature definitions.

`scripts/capture_security_lolm_native.py` hashes checkpoint bytes before
deserialization, loads with `torch.load(weights_only=True)`, requires
`strict=True` complete weights, seeds regime sampling per event and
refuses real-world event inputs. Run on a local trusted checkout, with
`torch`, `PyYAML`, and `tiktoken` installed:

```bash
python scripts/capture_security_lolm_native.py \
  --events runs/security_lab/study_001/reference-events.jsonl \
  --checkpoint /trusted/ckpt_26000.pt \
  --expected-sha <verified-independent-sha256> \
  --out-dir runs/security_lab/native_reference --device mps
```

Repeat for the held-out events with the same checkpoint and seed, then
apply `falsify` to the two output bundles. No original native pretrained
checkpoint was executed or evaluated here.
