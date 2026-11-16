# QIRA Causal Observatory — Product & Research Charter (2026-11-15)

**Public fictional preview:** https://qira-causal-observatory-research.bryanleonard237.workers.dev/
**Source:** cloudflare/causal-observatory/worker.js
**Reference engine:** lolm/security_research/causal.py
**Review branch:** research/artex-defense-lab-2026-11-15 (PR #59)

## The thesis

The enterprise question is not merely *"What looks dangerous?"* but
*"Which intervention should we choose, under which causal assumptions, with
what measurable effect, what cost, and what independently auditable proof?"*

The long-term ambition is a **counterfactual assurance network**:
event provenance -> hypothesized causal models -> calibrated uncertainty ->
safe intervention proposals -> actual intervention outcomes ->
third-party-verifiable evidence -> improved models.

This is a proposal, **not** a validated technology or company valuation.

## What exists

1. An isolated Cloudflare Worker running a fictional security cascade model.
2. Four explicitly **assumed** structural variants: primary, service-token
   fallback, alternate export, combined. This is not a reconstruction of
   an observed attack path.
3. Five illustrative, strictly whitelisted interventions. The Worker rejects
   arbitrary code, network targets, uploaded logs and unrecognized controls.
4. Robust control search over every 0..5-control subset. The displayed
   "frontier" is Pareto-nondominated in assumed **intervention cost units**
   and number of controls, not verified enterprise spend or risk reduction.
5. An interactive browser-based experiment with alternative-path sensitivity.
6. SHA-256 hash-linked evidence artifacts and a deterministic replay
   verification endpoint. This detects differences relative to the currently
   deployed model; **it is not a digital signature, inference attestation,
   immutable timestamp, or evidence that the structural equations are true**.
7. Independent Python and JS implementations and a fixed cross-language
   receipt digest checked in GitHub CI.
8. The older security-research pipeline: synthetic event stress tests, OCSF
   authentication adapter, NFET token-aligned observer, and falsification
   against shuffled traces.

No real-world security observations, customers, neural detection improvements,
or validated causal effects have been obtained.

## Why this is *not* currently unique

XM Cyber already markets digital-twin attack-path analysis, chokepoint
prioritization, remediation validation and business-impact scoring.
Gremlin already markets controlled reliability experiments and resilience
verification. We cannot pitch generic "simulate a breach and find the
best intervention" as a novel or billion-dollar moat.

Primary public competitive references (as of November 2026):
- https://xmcyber.com/platform/
- https://xmcyber.com/platform/remediation-operations/
- https://www.gremlin.com/product/chaos-engineering

## Potential differentiated wedge (must be demonstrated)

A **vendor-neutral, uncertainty-aware causal evidence exchange** which:
- Represents and propagates **competing causal hypotheses** rather than
  silently assuming a single correct dependency graph.
- Stores explicit counterfactual estimands, model versions, interventions
  and disconfirming observations (not just alerts and severity scores).
- Verifies that a fix changed an *observed outcome* in an authorized,
  contained setting, rather than confusing a simulated blocked edge with
  proof of prevention.
- Compares learned LOLM/NFET regime signals with trivial change detectors
  and standard models using held-out incidents and identical test budgets.
- Produces proof bundles with signed logs/attestations, chain of custody,
  independent verifiers and measured quality gates **only after** that
  infrastructure has been built and independently audited.
- Supports cross-domain adapters after security validation: cloud operations,
  supply-chain outages, traffic corridor resilience, and AI agent workflows.

## Nonnegotiable product boundary

No automated exploitation, credential acquisition, scanning arbitrary targets,
or running unapproved experiments in customer production. All data connectors
must be scoped to owner-authorized read-only evidence initially. Stateful
enterprise features require identity, RBAC, explicit tenant isolation, quotas,
retention controls, encryption, audit logs, and signed consent. Never put
private event logs in a public Worker or a general-purpose chatbot prompt.

## Cloudflare deployment architecture — proposed, not deployed

- **Workers**: authenticated query API, deterministic replay and receipt
  verification. This isolated fictional demonstration is the only deployed
  component today.
- **Access / Zero Trust**: company SSO and user/service authorization.
- **D1**: minimal experiment metadata and normalized model-version catalog.
- **R2**: encrypted, content-addressed, access-controlled evidence bundles.
- **Queues**: bounded background assessment jobs with idempotency keys.
- **Durable Objects**: serialized state per experiment/tenant for concurrency,
  if a real concurrency requirement is established.
- **AI Gateway / Workers AI**: optional assisted hypothesis generation;
  NEVER promote model-generated edges to proven causal facts.
- **WAF / rate limits**: quota enforcement and abuse prevention.
- **QEV / signed proofs**: future independently validated key and signing
  design, not present in the hash-only prototype.

Do not provision paid services or mutable production resources before
a tested requirement justifies them.

## Scientific measurement protocol

### 1 — Ingest and provenance
Normalize event timestamps, source clocks, entity IDs, data quality and
authorization. Separate observation from estimated latent state and human
interpretation. Tag missingness; preserve all alternative explanations.

### 2 — Graph identification
State precisely which causal edges are assumptions, experimentally
identified, or based on externally validated domain rules. Track
confounders, selection effects, temporal leakage and model version.

### 3 — Counterfactual audit
For each proposed defense: specify the target outcome and identification
assumptions. Compare multiple plausible graph structures and a placebo
intervention. If an effect changes sign across credible assumptions,
abstain rather than recommend a definitive action.

### 4 — Controlled outcome validation
With customer permission, run only bounded, non-disruptive experiments
against isolated replicas or sanctioned test environments. Compare to
appropriate matched baselines, randomized rollout where feasible and
pre-registered measurements.

### 5 — Honest evaluation
Track prevented incidents **only when actually observed/causally supported**,
false-alert volume, prediction calibration, intervention latency, operational
disruption, analyst minutes, coverage and data provenance. Measure
NFET's incremental effect separately. Account for confidence intervals
and false discovery control across repeated experiments.

## Commercial tests and rejection criteria

**First target:** platform security / incident-response engineering teams who
need defensible remediation decisions across multiple tools.

30-day test:
- Recruit five design partners with permission to use sanitized,
  rights-cleared lab data.
- Ask for past cases and a blinded ranking of what remediation would
  have minimized business impact.
- Compare against their current workflow and standard attack-path
  tooling. Avoid using labels that contain the final remediation recommendation.
- Measure a prospective outcome in a controlled environment before
  any savings, ROI or prevention claims.

90-day go/no-go gates:
- At least 2 independent organizations complete reproducible evaluations.
- An objectively defined improvement over baseline on pre-agreed metrics,
  with confidence estimates and documented limitations.
- Evidence an economic buyer would pay for a repeatable product workflow,
  not merely a compelling animation.
- Privacy/security review, observability, audit export and clear liability
  boundary before ingesting sensitive customer telemetry.

**Kill or pivot if:** intervention estimates are not identifiable, learned
NFET signals fail matched comparisons, independent replay cannot be trusted,
customers already have an equivalent validated workflow, or the product
introduces more operational risk than it reduces.

## Revenue is not a result yet

A multibillion-dollar outcome is *possible only if* the product establishes
defensible empirical superiority, customer trust, distribution and scalable
unit economics. A working research dashboard is an early prototype, not
proof of a massive market or revenue. Use discovery and paid design partners
to decide whether the next engineering dollar should go into this.
