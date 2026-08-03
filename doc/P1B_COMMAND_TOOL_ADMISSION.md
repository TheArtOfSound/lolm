# P1-B Command and Tool Admission Boundary

Parent: #42  
Workstream: #46

## Authority model

A model or caller may propose a command or structured tool call. It cannot authorize execution.

Every executable command must receive a `lolm.command_admission.v1` decision before process dispatch. Every model-issued JSON tool action must receive the same class of deterministic decision before list, read, write, edit, run, or finish handling.

## Mandatory boundaries

1. `admit_tool_call()` validates and canonicalizes the structured action.
2. A `run` or `write_and_run` action contains a nested `admit_command()` decision.
3. `CodeAgent` filters rejected actions before existing handlers can reach them.
4. `Sandbox.run()` independently recompiles the command decision.
5. CodeAgent passes the nested command fingerprint as an expected fingerprint.
6. Sandbox refuses before execution when its independently compiled fingerprint differs.
7. Admission decisions are attached to events and sealed code receipts.

## Decision classes

- `admitted`
- `command_policy_rejection`
- `tool_schema_rejection`
- `environment_rejection`
- `infrastructure_rejection` at the sandbox boundary
- `admission_receipt_mismatch` when structured and sandbox decisions disagree

Provider authentication, provider quota, rate limiting, upstream service rejection, and model-generation failure are outside this taxonomy. They occur before an executable proposal exists and must not be counted as command-competence failures.

## Contract fields

- task and source
- shell dialect and platform
- working directory and workspace root
- primary language
- known and expected files
- timeout
- verifier plan
- risk class
- isolation requirement
- network authority
- package-install authority

The contract, environment, normalized proposal, outcome, reason codes, and verifier plan receive stable SHA-256 fingerprints.

## Fail-closed rules

The admission layer rejects natural-language instructions masquerading as commands, Markdown command payloads, malformed quoting, shell-dialect mismatches, unsupported desktop openers, parent traversal, sensitive host paths, destructive or privileged operations, unapproved network access, unapproved package installation, unknown tool actions, unknown arguments, missing arguments, invalid argument types, and nested commands that fail admission.

Rejected structured actions are removed from the parsed turn before dispatch. A rejected primary proposal does not execute through a fallback path.

## Receipt data minimization

Source content and edit bodies are not copied verbatim into admission evidence. Their byte count and SHA-256 are retained. Command text and non-secret canonical arguments remain available for audit.

## Current gates

- 500 distinct adversarial command proposals
- direct `Sandbox.run()` bypass tests
- structured action filtering tests
- nested command admission tests
- cross-process and platform suites inherited from P1-A
- full repository and CLI/security workflows required on the clean product head

## Explicit non-goals

- adaptive routing remains off
- no provider or model changes
- no package publication
- no production deployment
- no retry-policy redesign in this workstream
