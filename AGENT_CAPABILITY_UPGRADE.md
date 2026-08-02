# LOLM Agent Capability Upgrade

Status: design and first deterministic components

Base commit: `ecc9a7a28713e1eee47821e1e8c3e51409670be1`

Tracking issue: #14

## Why this exists

LOLM currently has three separate quality failures that share one architectural cause:

1. It emits invalid commands because free-form model text is treated too closely to executable intent.
2. It answers questions incorrectly because retrieval, freshness, evidence, and abstention are not enforced as a single factuality pipeline.
3. It writes incorrect code because model selection and candidate ranking are based on static lists and shallow artifact-specific checks rather than measured task-bucket performance.

Adding more warnings to the system prompt will not solve this. The current coding prompt already contains a long catalogue of edge cases. More prose increases context pressure while still leaving the model responsible for command syntax, task classification, and self-verification.

## External systems studied

### mini-SWE-agent

The important lesson is not to copy its exact interface. It is to preserve a simple, linear, inspectable trajectory with independent command executions, explicit limits, and durable run serialization. Complex control logic must justify itself with measured gains.

### Aider

Aider's repository-map approach demonstrates that large-codebase performance depends on selecting the correct files and symbols before editing. LOLM needs a tree-sitter symbol/dependency map and token-budgeted context retrieval rather than repeatedly sending arbitrary file bodies.

### OpenHands

OpenHands separates the control surface from agent backends and execution environments. LOLM should expose a stable agent/runtime protocol so model routing, sandboxing, verification, and UI can evolve independently.

### SWE-bench ecosystem

SWE-bench Verified and SWE-smith provide concrete evaluation and trajectory sources for repository repair. They are not sufficient alone, so LOLM also needs native command, browser-artifact, factuality, conversation, and packaged-runtime suites.

## Hugging Face candidates

The following are benchmark candidates, not presumed winners:

- `Qwen/Qwen3-Coder-30B-A3B-Instruct`
- `Qwen/Qwen3-Coder-480B-A35B-Instruct`
- `mistralai/Devstral-Small-2507`
- `moonshotai/Kimi-K2-Instruct`
- `zai-org/GLM-4.5`
- `openai/gpt-oss-120b`
- `ibm-granite/granite-3.3-8b-instruct`

Retrieval candidates:

- `BAAI/bge-m3`
- `BAAI/bge-reranker-v2-m3`

Evaluation and training sources:

- `SWE-bench/SWE-bench_Verified`
- `princeton-nlp/SWE-bench`
- `SWE-bench/SWE-smith` and current language-specific successors
- `openai/openai_humaneval`
- `google-research-datasets/mbpp`
- `m-a-p/CodeFeedback-Filtered-Instruction`
- `NousResearch/hermes-function-calling-v1`

Licenses and dataset terms must be reviewed before training or redistribution.

## Target execution path

```text
User request
  -> task/freshness/risk profiler
  -> acceptance contract
  -> capability router
       planner model
       executor model
       independent verifier model
  -> repository/evidence retrieval
  -> typed action proposal
  -> deterministic command preflight/compiler
  -> isolated execution
  -> artifact-specific verifier registry
  -> evidence delta + failure fingerprint
  -> bounded repair or honest stop
  -> receipt with CLI SHA, server SHA, models, evidence, and terminal status
```

## Core design rules

### 1. Models propose. Deterministic systems decide.

Models may propose files, commands, plans, and answers. They may not decide that their own output is executable, factual, or complete.

### 2. No raw command reaches the sandbox without preflight.

The first implementation is `lolm.command_preflight`.

It detects:

- human instructions masquerading as commands;
- headless desktop-open attempts;
- Markdown contamination;
- `/bin/sh` versus Bash incompatibilities;
- Python execution or compilation of HTML/CSS/JS artifacts;
- broken quoting;
- stable execution failure classes and fingerprints.

A later action schema will replace most free-form shell generation with typed intents.

### 3. Routing is measured per task bucket.

The first implementation is `lolm.capability_router`.

It combines:

- hard capability floors;
- task and language requirements;
- provider availability;
- conservative model priors;
- rolling per-bucket pass and error rates;
- separate planner, executor, and verifier assignments;
- penalties for correlated self-verification.

A model with a stronger reputation must lose routing priority when LOLM's own evidence shows worse outcomes.

### 4. Verification is artifact-specific.

Examples:

- Python: parse/compile, imports, tests, contract probes.
- JavaScript: AST/syntax, tests, runtime output.
- HTML: DOM parse, script extraction, browser render, console errors, interaction smoke.
- Repository edits: existing tests, targeted regression tests, diff constraints, dependency checks.
- Factual answers: claim-evidence entailment, citation coverage, freshness, source conflict handling.

### 5. Repair requires a changed failure fingerprint.

Repeating a semantically equivalent command or rewrite is not progress. Each repair must alter the root-cause fingerprint, improve evidence, or consume a narrowly bounded diagnostic allowance.

### 6. Every route and result becomes calibration data.

Record privacy-safe fields:

- task bucket;
- role/model/provider;
- command preflight class;
- verifier evidence;
- failure fingerprint;
- steps and latency;
- shipped/stuck/broken;
- later user correction or acceptance when available.

This data updates model routing. It does not automatically train or deploy a model.

## Implementation sequence

### Slice A: deterministic command layer

- Integrate `inspect_command` before every model-originated run.
- Emit a `command_rejected` event with failure class and suggestion.
- Route HTML verification to internal verifiers.
- Add POSIX/Bash/PowerShell/cmd conformance corpora.

### Slice B: measured model routing

- Replace static ensemble ordering with `RoutePlan` assignments.
- Persist provider health and task-bucket performance.
- Add planner/executor/verifier model identities to receipts.
- Preserve a controlled exploration allocation for new models.

### Slice C: repository intelligence

- Add tree-sitter parsing and symbol extraction.
- Build definition/reference graph.
- Rank relevant files and symbols under a context budget.
- Require read-before-edit for existing files.
- Evaluate relevant-file recall independently of final patch success.

### Slice D: grounded QA

- Add freshness and evidence-requirement classifier.
- Implement lexical plus dense retrieval.
- Rerank retrieved passages.
- Build a sentence-level claim ledger.
- Refuse unsupported source-constrained claims and mark uncertainty elsewhere.

### Slice E: training and optimization

- Normalize LOLM trajectories into a stable schema.
- Curate successful and failed command/code/QA trajectories.
- Use public datasets only under compatible terms.
- Fine-tune or preference-train small routing/verifier models first.
- Consider executor fine-tuning only after the benchmark harness is stable.

## Release rule

The coding agent remains alpha until realistic repeated tasks recover. The CLI/receipt layer may remain a hardened beta only where its supported command surfaces and exclusions are explicit.

No part of this branch should merge because unit tests pass alone. Promotion requires the benchmark manifest, packaged CLI tests, SHA-pinned staging, and repeated organic runs.
