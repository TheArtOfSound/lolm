# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Verification Capability Graph (VCG).

Positive and negative environment facts. A definitive ENOENT / no-provider
result disables that tool edge for the remainder of the run unless the
environment fingerprint changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Canonical capability ids used by contracts and the code agent
KNOWN_CAPABILITIES = (
    "python3",
    "node",
    "html.render",       # headless Chromium / static lint
    "html.static_lint",
    "desktop.open",      # xdg-open / open — typically unavailable in jail
    "network.outbound",
    "pdf.exists",
    "pdf.validate",
    "syntax.python",
    "unittest",
    "pytest",
    "camera",
    "email",
)


@dataclass
class CapabilityFact:
    capability_id: str
    available: bool
    evidence: str = ""
    strength: str = "definitive"  # definitive | provisional | inferred
    alternatives: List[str] = field(default_factory=list)
    environment_fingerprint: str = ""
    observed_at: float = 0.0
    attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CapabilityFact":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


def environment_fingerprint(
    *,
    extra: Optional[Dict[str, Any]] = None,
    probe_bins: Optional[Sequence[str]] = None,
) -> str:
    """Stable fingerprint of the execution environment for negative-fact lifetime."""
    bins = list(probe_bins or ("python3", "node", "xdg-open", "chromium", "google-chrome", "playwright"))
    present = {b: bool(shutil.which(b)) for b in bins}
    payload = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "bins": present,
        "cwd_writable": os.access(os.getcwd(), os.W_OK),
        "extra": extra or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# Error signatures that prove a capability is unavailable (not a code bug)
_NEGATIVE_SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "desktop.open": (
        "xdg-open",
        "no application",
        "cannot open display",
        "no display",
        "gio: ",
        "failed to execute child process",
        "command not found: xdg-open",
        "xdg-open: not found",
        "no providers available",
        "unable to open",
        "bwrap:",
    ),
    "network.outbound": (
        "network is unreachable",
        "name or service not known",
        "temporary failure in name resolution",
        "connection refused",
        "nodename nor servname",
        "failed to establish a new connection",
        "urlopen error",
    ),
    "python3": ("python3: not found", "no such file or directory: 'python3'"),
    "node": ("node: not found", "no such file or directory: 'node'"),
}


class CapabilityGraph:
    """Graph of verifier/tool availability with negative-fact persistence."""

    def __init__(self, fingerprint: Optional[str] = None):
        self.fingerprint = fingerprint or environment_fingerprint()
        self.facts: Dict[str, CapabilityFact] = {}
        self._probe_defaults()

    def _probe_defaults(self) -> None:
        """Seed positive facts from the host without executing user tools."""
        if shutil.which("python3"):
            self.set_positive("python3", "which python3", strength="inferred")
            self.set_positive("syntax.python", "python3 available", strength="inferred")
            self.set_positive("unittest", "stdlib unittest", strength="inferred")
        if shutil.which("node"):
            self.set_positive("node", "which node", strength="inferred")
        # Headless HTML verify is a code-path capability (static lint always works)
        self.set_positive("html.static_lint", "static lint always available", strength="definitive")
        self.set_positive("html.render", "static lint or Chromium path", strength="provisional",
                          alternatives=["html.static_lint"])
        self.set_positive("pdf.exists", "filesystem check", strength="inferred")
        # Desktop open is usually unavailable in sandboxes — provisional until proven
        if not shutil.which("xdg-open") and not shutil.which("open"):
            self.set_negative(
                "desktop.open",
                "no xdg-open/open binary",
                alternatives=["html.render", "html.static_lint"],
            )

    def set_positive(
        self,
        capability_id: str,
        evidence: str,
        *,
        strength: str = "definitive",
        alternatives: Optional[List[str]] = None,
    ) -> CapabilityFact:
        fact = CapabilityFact(
            capability_id=capability_id,
            available=True,
            evidence=evidence[:500],
            strength=strength,
            alternatives=list(alternatives or []),
            environment_fingerprint=self.fingerprint,
            observed_at=time.time(),
            attempts=self.facts.get(capability_id, CapabilityFact(capability_id, True)).attempts,
        )
        self.facts[capability_id] = fact
        return fact

    def set_negative(
        self,
        capability_id: str,
        evidence: str,
        *,
        alternatives: Optional[List[str]] = None,
        strength: str = "definitive",
    ) -> CapabilityFact:
        prev = self.facts.get(capability_id)
        attempts = (prev.attempts + 1) if prev else 1
        fact = CapabilityFact(
            capability_id=capability_id,
            available=False,
            evidence=evidence[:500],
            strength=strength,
            alternatives=list(alternatives or (prev.alternatives if prev else [])),
            environment_fingerprint=self.fingerprint,
            observed_at=time.time(),
            attempts=attempts,
        )
        self.facts[capability_id] = fact
        return fact

    def is_available(self, capability_id: str) -> Optional[bool]:
        f = self.facts.get(capability_id)
        if f is None:
            return None
        if f.environment_fingerprint != self.fingerprint and not f.available:
            # Fingerprint changed — invalidate negative
            return None
        return f.available

    def may_attempt(self, capability_id: str) -> Tuple[bool, str]:
        """Return whether executing this capability is allowed.

        Definitive negatives: only one attempt per environment fingerprint.
        """
        f = self.facts.get(capability_id)
        if f is None:
            return True, "unknown — first attempt allowed"
        if f.environment_fingerprint != self.fingerprint:
            return True, "environment fingerprint changed — re-probe allowed"
        if f.available:
            return True, "capability available"
        if f.strength == "definitive" and f.attempts >= 1:
            alts = ", ".join(f.alternatives) or "none"
            return False, (
                f"capability {capability_id} unavailable (definitive): {f.evidence[:120]}; "
                f"alternatives: {alts}"
            )
        return True, "provisional negative — one more attempt allowed"

    def observe_command_result(
        self,
        command: str,
        *,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ) -> Optional[CapabilityFact]:
        """Promote environmental failures into negative capability facts."""
        blob = f"{command}\n{stdout}\n{stderr}".lower()
        cmd = (command or "").strip().lower()

        # Map common commands to capability ids
        cap: Optional[str] = None
        if cmd.startswith("xdg-open") or cmd.startswith("open ") or "xdg-open" in cmd:
            cap = "desktop.open"
        elif any(x in cmd for x in ("curl ", "wget ", "httpx", "requests.get", "urllib")):
            cap = "network.outbound"

        if cap is None:
            # Signature scan
            for cid, sigs in _NEGATIVE_SIGNATURES.items():
                if any(s in blob for s in sigs):
                    cap = cid
                    break

        if cap is None:
            return None

        # Success → positive
        if exit_code == 0 and not any(
            s in blob for s in _NEGATIVE_SIGNATURES.get(cap, ())
        ):
            return self.set_positive(cap, f"command ok: {command[:80]}")

        # Failure matching negative signatures → definitive negative
        sigs = _NEGATIVE_SIGNATURES.get(cap, ())
        if any(s in blob for s in sigs) or (
            cap == "desktop.open" and exit_code != 0
        ):
            alts = ["html.render", "html.static_lint"] if cap == "desktop.open" else []
            return self.set_negative(
                cap,
                f"cmd={command[:80]} exit={exit_code} err={(stderr or stdout)[:200]}",
                alternatives=alts,
                strength="definitive",
            )
        return None

    def resolve(
        self,
        verifiers: Sequence[str],
    ) -> Dict[str, Any]:
        """Resolve required verifiers against the graph.

        Returns hard_missing, substitutes, and allowed execution plan.
        """
        hard_missing: List[str] = []
        substitutes: Dict[str, str] = {}
        plan: List[Dict[str, str]] = []
        for v in verifiers:
            avail = self.is_available(v)
            if avail is True:
                plan.append({"verifier": v, "via": v})
                continue
            if avail is False:
                fact = self.facts[v]
                alt = next((a for a in fact.alternatives if self.is_available(a) is not False), None)
                if alt:
                    substitutes[v] = alt
                    plan.append({"verifier": v, "via": alt})
                else:
                    hard_missing.append(v)
            else:
                # Unknown — allow attempt
                plan.append({"verifier": v, "via": v, "probe": "true"})
        return {
            "hard_missing": hard_missing,
            "substitutes": substitutes,
            "plan": plan,
            "fingerprint": self.fingerprint,
        }

    def available_set(self) -> Set[str]:
        return {k for k, f in self.facts.items()
                if f.available and f.environment_fingerprint == self.fingerprint}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "facts": {k: v.to_dict() for k, v in self.facts.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CapabilityGraph":
        g = cls(fingerprint=(d or {}).get("fingerprint"))
        for k, v in ((d or {}).get("facts") or {}).items():
            g.facts[k] = CapabilityFact.from_dict(v)
        return g
