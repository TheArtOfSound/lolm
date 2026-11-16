# Event Horizon — Commercial and Scientific Thesis

**Working thesis, dated 2026-11-15. Not investment guidance or proof of product-market fit.**

## The target

A **defensive decision verification network** that helps an organization
choose the smallest set of safety controls that can be shown to reduce
real loss, without imposing unnecessary friction on legitimate users.

This is materially different from yet another dashboard of suspected attacks,
though adjacent tools already exist. The core product question is:

> Under defensible assumptions, which permitted defensive intervention
> materially improves a measured outcome, with how much uncertainty and
> what operational cost?

## Competitive truth

This is not a greenfield market. Cymulate, Picus, AttackIQ, Pentera,
Horizon3.ai, SafeBreach, and other providers already perform attack-path
validation, adversary emulation, exposure management, and control testing.
Some also optimize mitigations and correlate business context.
The idea is not globally unique; any differentiation must be *demonstrated*.

References for competitor claims:
- https://www.gartner.com/reviews/market/adversarial-exposure-validation
- https://www.mordorintelligence.com/industry-reports/adversary-emulation-platform-market

Avoid competing on quantity of synthetic attacks or an unspecified AI model.
That would put Qira against better-financed incumbent content libraries.

## The proposed moat (each layer conditional on proof)

1. **Bitemporal evidence graph.** Separate incident time, detection time,
   publication time, analyst verification, and model inference. Keep uncertain
   and refuted reports visible instead of treating all headlines as fact.
2. **Counterfactual defensive twin.** Represent a control as a scoped,
   reviewable intervention. Compare predicted attack interruption against
   collateral harm to legitimate activity.
3. **Assumption uncertainty atlas.** Stress policy choices under broken
   instrumentation, incomplete permissions, silent fallback and untrusted
   approval metadata; communicate ignorance explicitly.
4. **LOLM/NFET shadow intelligence.** Use actual frozen latent state, gate,
   drift, entropy, memory and regime dynamics as *candidate* predictors.
   Require matched classical baselines, ablations and independent tests.
5. **Verifiable receipts.** Evidence originates from a trusted local
   or tenant-controlled boundary; signed attestations, independent replay
   and tamper-evident storage replace self-asserted model outputs.
6. **A policy-outcome learning network.** With explicit permission and
   contractually valid rights, learn from repeated *verified* outcomes
   across disjoint organizations—while preserving tenant segregation.
   This cannot be built from synthetic fixtures alone.

## Existing Qira assets to connect, and where NOT to connect

- LOLM: controlled inference and research ablations, read-only by default
- NFET: measure transition signals; do not claim causality from Phi alone
- WeSearch.press: headline **claims and timestamps**, never proof of intrusion
- DataSupply.shop: opt-in, licensed, provenance-tagged data transport
- QEV/QAL: receipt anchoring candidate; only after its verification
  and key management are independently audited
- Cloudflare: public Workers proof-of-concept now; private authenticated
  Access + D1/R2/Queues + per-tenant isolation later

Do NOT mix public research Worker, production secrets, real customers,
unverified news articles, and LOLM model logs in one data environment.

## A realistic commercialization wedge

Start with **identity and SaaS control-change assurance** for small
security teams or managed service providers. Ask whether a proposed
identity/WAF/token policy reduces a verified abuse pattern and what
legitimate activity it would interrupt. Deliver a signed, repeatable
policy-change dossier—not generic 'risk score: 82'.

No autonomous pentesting or cross-tenant scanning. Every data connector
must be authorized and least-privilege. A provider that cannot share
necessary telemetry is ineligible for claimed verification.

### 30-day build/validation gate

- Keep the synthetic public demo running and stable
- Run accessibility, mobile and API contract checks on live site
- Instrument an authenticated **internal-only** Cloudflare safety inventory
  in Qira-owned scopes, without exposing request IPs or credentials publicly
- Create a real trace provenance manifest and frozen-LOLM checkpoint run
- Document failure modes and threat model

### 60-day product gate

- Obtain three qualified design partners (security leads/MSPs)
- Run controlled, consented tests on tenant-owned synthetic/staged systems
- Measure work time, false blocks, actual decision changes and evidence quality
- Compare to what the same team can get from existing tools
- Do not market prevented-loss estimates until validated against outcomes

### 90-day economic gate

- Seek one or more paid pilot contracts contingent on meaningful value
- Measure retention, decision reuse, gross margin, onboarding time and
  total integration cost
- Convert only reliable capabilities into paid packages
- Stop, narrow or pivot if there is no paid problem with defensible advantage

Illustrative discovery questions (not price facts): would a team pay
$2,000–$10,000 for a time-bounded evidence pilot; which organizational
budget owns the purchase; what specific control-change decision would
justify that spend? Validate with customers before treating prices as real.

## Scientific pass/fail rules

A **positive result** must survive:
- held-out incidents split by organization and time
- precision, incident recall, false alerts per host-day, and detection delay
- off-policy control drift and intervention-confounding analysis
- neural-vs-nonneural equal-budget ablations
- model- and data-origin attestation
- calibration checks and uncertainty bounds
- explicit replication on a second environment
- legitimate workflow disruption and analyst overhead measurement

A **negative** result is recorded with the same visibility as a positive one.

## Architecture

Public research plane:
```
Browser / MCP client
    -> Cloudflare Worker (synthetic only, stateless)
       -> Deterministic scenario engine
       -> Policy Pareto enumeration (32)
       -> Assumption stress atlas (6 worlds)
       -> SHA-256 receipt
```

A *future*, separate enterprise plane (not deployed):
```
Authenticated authorized tenant
    -> Cloudflare Access / scoped service identity
    -> Tenant-isolated ingestion Worker (strict schemas)
    -> Cloudflare Queue
       -> D1 metadata + customer rights and source manifest
       -> Encrypted, isolated R2 evidence
       -> Durable Object receipt sequencer / signature service
       -> Offline/read-only LOLM/NFET inference
       -> Reproducible counterfactual defense comparison
    -> Signed control decision dossier + customer export
```

The data plane requires careful retention, least privilege, quotas,
auditing, consent, and external security review. Nothing above authorizes
interacting with unrelated organizations.

## Honest billion-dollar standard

A billion-dollar valuation does not follow from a novel technical demo.
It would require a large defensible market, strong enterprise retention,
trusted outcomes, distribution, high contract values and operating leverage.
The immediate milestone is a verified paid customer decision, not a
valuation target.

## Main risks

- Structural assumptions about threats are wrong or incomplete
- An authorized insider path is not preventable by modeled identity controls
- Explaining predicted loss looks causal even when it is not
- Self-reported receipts falsely imply independent authenticity
- Security products have long sales cycles, privacy exposure and audit cost
- Incumbents can copy surface-level simulation dashboards
- Invalid real data rights can make a data network commercially unusable

**Stop condition:** no reproducible lift versus a simpler baseline, no
measurable customer decision improvement, or excessive legitimate
workflow harm. Do not hide these results to preserve the thesis.
