"""Offline NFET token-trace observer for defensive security research.

Consumes externally generated LOLM-NFET per-token telemetry. It DOES NOT
run a model and cannot attest that a stated model produced the trace.
Local checkpoint SHA-256 verification proves only the bytes of that file.
The shadow detector never executes tools or modifies production systems.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable, Sequence

from .lab import Event, canonical

MAX_TOKENS = 400_000
MAX_TOKENS_PER_EVENT = 4096
MAX_TRACE_LINE = 4096
HEX256 = re.compile(r"^[0-9a-f]{64}$")
CHANNELS = ("entropy_change", "hidden_drift", "gate_change", "regime_change")
FLOORS = (0.10, 0.02, 0.01, 0.05)


def security_event_hash(events: Sequence[Event]) -> str:
    """Bind event content while excluding all evaluation labels."""
    payload = [{k: v for k, v in asdict(e).items() if k != "truth"} for e in events]
    return hashlib.sha256(canonical(payload)).hexdigest()


@dataclass(frozen=True)
class NFETToken:
    event_index: int
    token_index: int
    logit_entropy: float
    hidden_drift: float
    gate_mean: float
    regime_entropy: float

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "NFETToken":
        if not isinstance(raw, dict):
            raise ValueError("token must be an object")
        if set(raw) != set(cls.__dataclass_fields__):
            raise ValueError("token must contain exactly the NFET trace fields")
        for key in ("event_index", "token_index"):
            if type(raw[key]) is not int or raw[key] < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
        if raw["token_index"] >= MAX_TOKENS_PER_EVENT:
            raise ValueError("token_index exceeds per-event ceiling")
        bounds = {"logit_entropy": (0, 200), "hidden_drift": (0, 1_000_000),
                  "gate_mean": (0, 1), "regime_entropy": (0, 20)}
        for key, (lower, upper) in bounds.items():
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be numeric")
            if not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f"{key} is not finite or exceeds limits")
        return cls(**{k: float(v) if k in bounds else v for k, v in raw.items()})


def parse_tokens(lines: Iterable[str], event_count: int) -> list[NFETToken]:
    if event_count < 1:
        raise ValueError("cannot align an empty event set")
    result: list[NFETToken] = []
    previous = (-1, -1)
    seen: set[int] = set()
    for line_no, line in enumerate(lines, 1):
        if line_no > MAX_TOKENS or len(line.encode("utf-8")) > MAX_TRACE_LINE:
            raise ValueError("token trace size limit exceeded")
        if not line.strip():
            continue
        try:
            token = NFETToken.parse(json.loads(line))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid token at line {line_no}: {exc}") from exc
        if token.event_index >= event_count:
            raise ValueError("trace references a nonexistent event")
        if (token.event_index, token.token_index) <= previous:
            raise ValueError("tokens must be sorted, unique and event-aligned")
        if token.event_index != previous[0] and token.token_index != 0:
            raise ValueError("each event's token_index must start at zero")
        if token.event_index == previous[0] and token.token_index != previous[1] + 1:
            raise ValueError("token sequence has an index gap")
        previous = (token.event_index, token.token_index)
        result.append(token)
        seen.add(token.event_index)
    if seen != set(range(event_count)):
        raise ValueError("each security event requires at least one token")
    return result


def trace_digest(tokens: Sequence[NFETToken]) -> str:
    return hashlib.sha256(canonical([asdict(t) for t in tokens])).hexdigest()


def check_manifest(manifest: dict[str, Any], events: Sequence[Event],
                   tokens: Sequence[NFETToken], *, checkpoint_path: Path | None = None,
                   expected_checkpoint: str | None = None) -> dict[str, Any]:
    """Verify trace/event hashes and optional pinned checkpoint file bytes.

    This does not authenticate the process that generated the telemetry.
    """
    if not isinstance(manifest, dict) or manifest.get("schema") != "lolm-nfet-observer/v1":
        raise ValueError("unsupported observer manifest schema")
    if manifest.get("source_type") not in {"synthetic", "checkpoint-generated"}:
        raise ValueError("source_type must be synthetic or checkpoint-generated")
    for key in ("events_sha256", "trace_sha256"):
        if not isinstance(manifest.get(key), str) or not HEX256.fullmatch(manifest[key]):
            raise ValueError(f"invalid {key}")
    if manifest["events_sha256"] != security_event_hash(events):
        raise ValueError("manifest/event mismatch")
    if manifest["trace_sha256"] != trace_digest(tokens):
        raise ValueError("manifest/trace mismatch")
    chk = manifest.get("checkpoint_sha256")
    if chk is not None and (not isinstance(chk, str) or not HEX256.fullmatch(chk)):
        raise ValueError("invalid checkpoint SHA-256")
    if manifest["source_type"] == "checkpoint-generated" and not chk:
        raise ValueError("checkpoint-generated trace requires checkpoint_sha256")
    if expected_checkpoint is not None:
        if not HEX256.fullmatch(expected_checkpoint):
            raise ValueError("expected checkpoint must be 64 lowercase hex characters")
        if chk != expected_checkpoint:
            raise ValueError("checkpoint does not match independent expected SHA-256 pin")
    checkpoint_bytes_verified = False
    if checkpoint_path is not None:
        if chk is None or expected_checkpoint is None:
            raise ValueError("checkpoint verification requires both manifest and expected SHA-256")
        digest = hashlib.sha256()
        with checkpoint_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != expected_checkpoint:
            raise ValueError("checkpoint bytes do not match expected SHA-256")
        checkpoint_bytes_verified = True
    return {
        "event_binding_verified": True, "trace_binding_verified": True,
        "checkpoint_bytes_verified": checkpoint_bytes_verified,
        "trace_origin_attested": False,
        "origin_claim": manifest["source_type"],
        "checkpoint_sha256": chk,
    }


def event_features(tokens: Sequence[NFETToken], event_count: int) -> list[tuple[float, ...]]:
    """Compute event-aligned summary features using only current/past events."""
    groups: list[list[NFETToken]] = [[] for _ in range(event_count)]
    for token in tokens:
        if not 0 <= token.event_index < event_count:
            raise ValueError("token/event index mismatch")
        groups[token.event_index].append(token)
    if any(not group for group in groups):
        raise ValueError("missing token telemetry for an event")
    features: list[tuple[float, ...]] = []
    prev: tuple[float, float, float, float] | None = None
    for group in groups:
        curr = (
            statistics.fmean(t.logit_entropy for t in group),
            statistics.fmean(t.hidden_drift for t in group),
            statistics.fmean(t.gate_mean for t in group),
            statistics.fmean(t.regime_entropy for t in group),
        )
        features.append((
            abs(curr[0] - prev[0]) if prev else 0.0,
            curr[1],
            abs(curr[2] - prev[2]) if prev else 0.0,
            abs(curr[3] - prev[3]) if prev else 0.0,
        ))
        prev = curr
    return features


@dataclass(frozen=True)
class Calibration:
    centers: tuple[float, float, float, float]
    scales: tuple[float, float, float, float]
    threshold: float
    alpha: float
    benign_count: int
    reference_count: int
    calibration_count: int
    event_digest: str


def _score(values: Sequence[float], centers: Sequence[float], scales: Sequence[float]) -> float:
    return max(abs(x - c) / s for x, c, s in zip(values, centers, scales))


def fit_benign(events: Sequence[Event], tokens: Sequence[NFETToken],
               alpha: float = 0.1) -> Calibration:
    """Fit robust centers on first half, threshold on disjoint second half.

    Reference/calibration are temporally separated. Coverage only holds
    under additional exchangeability assumptions, not guaranteed by code.
    """
    if not 0 < alpha < 1 or not math.isfinite(alpha):
        raise ValueError("alpha must be in (0,1)")
    if len(events) < 40 or any(e.truth for e in events):
        raise ValueError("calibration requires >=40 explicitly benign events")
    features = event_features(tokens, len(events))
    midpoint = len(features) // 2
    reference, calibration = features[:midpoint], features[midpoint:]
    centers = tuple(statistics.median(x[d] for x in reference) for d in range(4))
    scales = tuple(
        max(FLOORS[d], 1.4826 * statistics.median(abs(x[d] - centers[d]) for x in reference))
        for d in range(4)
    )
    scores = sorted(_score(x, centers, scales) for x in calibration)
    k = math.ceil((len(scores) + 1) * (1 - alpha)) - 1
    threshold = scores[k] if k < len(scores) else float("inf")
    return Calibration(centers=centers, scales=scales, threshold=threshold,
                       alpha=alpha, benign_count=len(events),
                       reference_count=midpoint, calibration_count=len(calibration),
                       event_digest=security_event_hash(events))


def shadow_evaluate(calibration: Calibration, calibration_events: Sequence[Event],
                    test_events: Sequence[Event], test_tokens: Sequence[NFETToken]) -> dict[str, Any]:
    """Read-only shadow classification; test labels used for metrics only."""
    if security_event_hash(calibration_events) != calibration.event_digest:
        raise ValueError("calibration events changed after fitting")

    def row_digest(e: Event) -> str:
        return hashlib.sha256(canonical({k: v for k, v in asdict(e).items() if k != "truth"})).hexdigest()

    calibration_rows = {row_digest(e) for e in calibration_events}
    if any(row_digest(e) in calibration_rows for e in test_events):
        raise ValueError("train/test event overlap; scenario separation required")
    if not test_events:
        raise ValueError("test events empty")
    features = event_features(test_tokens, len(test_events))
    scores = [_score(x, calibration.centers, calibration.scales) for x in features]
    predicted = [v > calibration.threshold for v in scores]
    tp = sum(p and e.truth for p, e in zip(predicted, test_events))
    fp = sum(p and not e.truth for p, e in zip(predicted, test_events))
    fn = sum(not p and e.truth for p, e in zip(predicted, test_events))
    tn = sum(not p and not e.truth for p, e in zip(predicted, test_events))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "mode": "nfet-telemetry-shadow", "execution_enabled": False,
        "checkpoint_forward_invoked": False,
        "calibration_event_sha256": calibration.event_digest,
        "test_event_sha256": security_event_hash(test_events),
        "alpha_requested": calibration.alpha,
        "threshold": calibration.threshold if math.isfinite(calibration.threshold) else None,
        "counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "metrics": {
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4)
                  if precision + recall else 0.0,
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        },
        "alerts": [
            {"event_index": i, "ts": e.ts, "score": round(v, 4)}
            for i, (e, v, p) in enumerate(zip(test_events, scores, predicted)) if p
        ],
        "scientific_limit": (
            "trace-origin unverified; split reference/calibration; "
            "exchangeability of test vs calibration is unverified"
        ),
    }
