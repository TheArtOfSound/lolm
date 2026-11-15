"""Falsification controls for offline event-aligned NFET security telemetry.

No network, no model calls, no incident attribution. A matched experiment uses
one trained-on-benign calibration for all event-shuffle controls. Scenario-level
label permutations preserve the number of positive scenarios (not individual
events), so overlapping events from a single incident aren't treated as
independent samples.

This module must *not* be used to claim operational detection accuracy from
synthetic data, or model authenticity from user-supplied trace metadata.
"""
from __future__ import annotations

from itertools import combinations
import random
from typing import Any, Sequence

from .lab import Event
from .observer import NFETToken, fit_benign, shadow_evaluate, security_event_hash, trace_digest
from .stress import Case


def _validate_scenarios(events: Sequence[Event], cases: Sequence[Case]) -> None:
    if not cases or not events:
        raise ValueError("event-level data and scenarios are required")
    expected = 0
    for case in cases:
        if not isinstance(case.name, str) or not case.name or not isinstance(case.incident, bool):
            raise ValueError("invalid scenario metadata")
        if case.start != expected or not case.start < case.end <= len(events):
            raise ValueError("scenarios must be contiguous, ordered and nonoverlapping")
        if any(event.truth != case.incident for event in events[case.start:case.end]):
            raise ValueError("event labels disagree with scenario label")
        expected = case.end
    if expected != len(events) or len({c.name for c in cases}) != len(cases):
        raise ValueError("scenarios must cover all test events with unique names")
    if sum(c.incident for c in cases) == 0 or all(c.incident for c in cases):
        raise ValueError("both positive and negative test scenarios required")


def shuffle_event_traces(tokens: Sequence[NFETToken], event_count: int, seed: int) -> list[NFETToken]:
    """Shuffle full token blocks, preserving each block's within-event order.

    This changes only which event owns each observation, not the distribution
    of model telemetry. An event-shuffle null asks whether *alignment* matters.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    groups: list[list[NFETToken]] = [[] for _ in range(event_count)]
    for tok in tokens:
        if not 0 <= tok.event_index < event_count:
            raise ValueError("token references an invalid event")
        groups[tok.event_index].append(tok)
    if any(not group for group in groups):
        raise ValueError("every event must have telemetry")
    order = list(range(event_count))
    random.Random(seed).shuffle(order)
    out: list[NFETToken] = []
    for new_index, old_index in enumerate(order):
        for new_token_index, tok in enumerate(groups[old_index]):
            out.append(NFETToken(event_index=new_index, token_index=new_token_index,
                                 logit_entropy=tok.logit_entropy, hidden_drift=tok.hidden_drift,
                                 gate_mean=tok.gate_mean, regime_entropy=tok.regime_entropy))
    return out


def _scenario_hits(alert_indices: set[int], scenarios: Sequence[Case]) -> list[bool]:
    return [any(i in alert_indices for i in range(c.start, c.end)) for c in scenarios]


def _scenario_stat(hits: Sequence[bool], positives: Sequence[bool]) -> float:
    n_pos = sum(positives)
    n_neg = len(positives)-n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("need both outcome groups")
    return sum(h for h,p in zip(hits,positives) if p)/n_pos - sum(h for h,p in zip(hits,positives) if not p)/n_neg


def exact_scenario_permutation_p(hits: Sequence[bool], labels: Sequence[bool]) -> dict[str, Any]:
    """Exact, *descriptive* scenario-label permutation test, one-sided.

    Null assumes exchangeable scenario labels (often implausible). It does not
    establish calibrated statistical significance on heterogeneous incidents.
    """
    if len(hits) != len(labels) or not hits or not all(type(v) is bool for v in (*hits,*labels)):
        raise ValueError("scenario hits and labels must be equal-length boolean vectors")
    n = len(hits)
    positives = sum(labels)
    if positives == 0 or positives == n or n > 18:
        raise ValueError("must have mixed labels and <=18 scenarios")
    observed = _scenario_stat(hits, labels)
    extreme = 0
    total = 0
    for subset in combinations(range(n), positives):
        simulated = [i in subset for i in range(n)]
        stat = _scenario_stat(hits, simulated)
        extreme += int(stat >= observed - 1e-12)
        total += 1
    return {"observed_difference": round(observed, 6),
            "one_sided_p": round(extreme/total, 6),
            "permutations": total,
            "assumptions": "scenario-label exchangeability is unverified; exploratory only"}


def _summary(alert_indices: set[int], scenarios: Sequence[Case]) -> dict[str, Any]:
    labels = [c.incident for c in scenarios]
    hits = _scenario_hits(alert_indices, scenarios)
    positives = sum(labels)
    negatives = len(labels)-positives
    return {"incident_recall": round(sum(h and p for h,p in zip(hits,labels))/positives,4),
            "benign_case_false_alert_rate": round(sum(h and not p for h,p in zip(hits,labels))/negatives,4),
            "scenario_hits": dict(zip((c.name for c in scenarios),hits)),
            "permutation": exact_scenario_permutation_p(hits, labels)}


def evaluate_falsification(
    reference_events: Sequence[Event],
    reference_tokens: Sequence[NFETToken],
    heldout_events: Sequence[Event],
    heldout_tokens: Sequence[NFETToken],
    scenarios: Sequence[Case],
    seeds: Sequence[int] = (11, 23, 37, 41, 53, 71, 89),
    alpha: float = 0.1,
) -> dict[str, Any]:
    _validate_scenarios(heldout_events, scenarios)
    if not seeds or len(seeds) > 50 or len(set(seeds)) != len(seeds):
        raise ValueError("provide 1..50 unique shuffle seeds")
    if any(type(seed) is not int for seed in seeds):
        raise ValueError("seeds must be integers")
    calibration = fit_benign(reference_events, reference_tokens, alpha=alpha)
    aligned = shadow_evaluate(calibration, reference_events, heldout_events, heldout_tokens)
    aligned_alerts = {a["event_index"] for a in aligned["alerts"]}
    aligned_summary = _summary(aligned_alerts, scenarios)
    shuffled = []
    for seed in seeds:
        tokens = shuffle_event_traces(heldout_tokens, len(heldout_events), seed)
        control = shadow_evaluate(calibration, reference_events, heldout_events, tokens)
        found = {a["event_index"] for a in control["alerts"]}
        shuffled.append({"seed": seed, "alerts": len(found),
                         **_summary(found, scenarios)})
    observed = aligned_summary["permutation"]["observed_difference"]
    # Conservative empirical control: not a statistical p value or a model gain.
    not_better_than_shuffled = sum(x["permutation"]["observed_difference"] >= observed - 1e-12 for x in shuffled)
    return {
        "schema": "lolm-nfet-falsification/v1",
        "source": "offline supplied traces; origin not authenticated",
        "model_forward_executed_here": False,
        "matched_calibration": True,
        "event_digest": security_event_hash(heldout_events),
        "trace_digest": trace_digest(heldout_tokens),
        "calibration_event_digest": calibration.event_digest,
        "reference_events": len(reference_events),
        "heldout_events": len(heldout_events),
        "scenarios": len(scenarios),
        "calibration_alpha": alpha,
        "aligned": {"counts": aligned["counts"], "event_metrics": aligned["metrics"],
                    **aligned_summary},
        "shuffled_controls": shuffled,
        "shuffle_control_exceedance": {
            "controls_at_least_as_discriminative": not_better_than_shuffled,
            "controls": len(shuffled),
            "fraction": round(not_better_than_shuffled/len(shuffled), 4),
            "note": "noninferential small-sample diagnostic; not a p-value"
        },
        "claim_gate": "not_met: no verified trained checkpoint, no independent real incidents",
    }
