"""Research-only fictional structural causal security intervention engine.

No operational telemetry, network access, or inferred real causal effects.
Edges and alternate pathways are researcher assumptions. Calculated outcomes
are effects inside these equations only, not empirical effectiveness.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import combinations
import json

VERSION = "causal-observatory/scm-1.0"
CONTROL_COSTS = {
    "step_up_auth": 2,
    "revoke_service_token": 3,
    "least_privilege": 6,
    "export_guard": 3,
    "egress_guard": 7,
}
VARIANTS = ("primary", "token_fallback", "shadow_export", "combined")


@dataclass(frozen=True)
class Context:
    compromised_identity: bool = True
    elevated_access_required: bool = True
    exposed_service_token: bool = True
    export_requested: bool = True
    sensitive_egress_attempted: bool = True
    authorized_workflow: bool = False

    def __post_init__(self):
        if any(type(v) is not bool for v in asdict(self).values()):
            raise ValueError("context variables must be booleans")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def structural(context: Context, controls=(), variant="primary"):
    if not isinstance(context, Context) or variant not in VARIANTS:
        raise ValueError("invalid context or structural variant")
    controls = tuple(controls)
    if len(set(controls)) != len(controls) or any(c not in CONTROL_COSTS for c in controls):
        raise ValueError("unsupported or duplicate interventions")
    active = set(controls)
    fallback = variant in ("token_fallback", "combined")
    shadow = variant in ("shadow_export", "combined")
    entry = (
        context.compromised_identity and "step_up_auth" not in active
    ) or (fallback and context.exposed_service_token and "revoke_service_token" not in active)
    privileged = entry and context.elevated_access_required and "least_privilege" not in active
    export = privileged and context.export_requested and ("export_guard" not in active or shadow)
    egress = export and context.sensitive_egress_attempted and "egress_guard" not in active
    return {
        "variant": variant,
        "entry": bool(entry),
        "privileged": bool(privileged),
        "bulk_export": bool(export),
        "sensitive_egress": bool(egress),
        "adverse_outcome": bool(egress and not context.authorized_workflow),
        "intervention_cost_units": sum(CONTROL_COSTS[c] for c in controls),
        "authorized_workflow": context.authorized_workflow,
    }


def replay(context: Context, interventions=(), variants=VARIANTS):
    interventions = tuple(sorted(interventions))
    variants = tuple(variants)
    if not variants or len(set(variants)) != len(variants) or any(v not in VARIANTS for v in variants):
        raise ValueError("invalid variants")
    baseline = {v: structural(context, (), v) for v in variants}
    altered = {v: structural(context, interventions, v) for v in variants}
    return {
        "version": VERSION,
        "scenario": "fictional-security-cascade",
        "assumptions": [
            "Edges and bypasses are researcher assumptions",
            "Intervention outcomes are simulated, not observed",
            "Costs are illustrative units, not dollars",
        ],
        "interventions": interventions,
        "baseline": baseline,
        "counterfactual": altered,
        "prevented_variants": [
            v for v in variants
            if baseline[v]["adverse_outcome"] and not altered[v]["adverse_outcome"]
        ],
        "robust_prevention": all(not v["adverse_outcome"] for v in altered.values()),
        "cost": sum(CONTROL_COSTS[c] for c in interventions),
    }


def frontier(context: Context, variants=VARIANTS):
    names = sorted(CONTROL_COSTS)
    feasible = []
    for count in range(len(names)+1):
        for intervention in combinations(names, count):
            experiment = replay(context, intervention, variants)
            if experiment["robust_prevention"]:
                feasible.append({
                    "controls": list(intervention),
                    "cost": experiment["cost"],
                    "count": count,
                    "prevented_variants": experiment["prevented_variants"],
                })
    result = [
        candidate for candidate in feasible
        if not any(
            other["cost"] <= candidate["cost"] and other["count"] <= candidate["count"]
            and (other["cost"] < candidate["cost"] or other["count"] < candidate["count"])
            for other in feasible
        )
    ]
    return sorted(result, key=lambda c: (c["cost"], c["count"], c["controls"]))


def receipt(previous_hash: str, experiment: dict):
    if type(previous_hash) is not str or len(previous_hash)!=64 or any(c not in "0123456789abcdef" for c in previous_hash):
        raise ValueError("invalid previous hash")
    data = {
        "previous_hash": previous_hash,
        "version": VERSION,
        "experiment_sha256": sha256(canonical(experiment)).hexdigest(),
    }
    return {**data, "hash": sha256(canonical(data)).hexdigest()}


def verify(experiments, receipts):
    if len(experiments)!=len(receipts):
        return False
    prev = "0"*64
    for exp, candidate in zip(experiments,receipts):
        if candidate != receipt(prev, exp):
            return False
        prev = candidate["hash"]
    return True


def demo(controls=()):
    scenario = Context()
    experiment = replay(scenario, controls)
    extras = {"version": VERSION, "frontier": frontier(scenario)}
    first = receipt("0"*64,experiment)
    second = receipt(first["hash"],extras)
    return {
        "experiment": experiment, "frontier": extras["frontier"],
        "receipts": [first, second],
        "receipts_verified": verify([experiment,extras],[first,second]),
        "observational_causality_established": False,
    }
