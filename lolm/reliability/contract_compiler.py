# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Dynamic Contract Compiler (DCC) — compile user language into structured criteria.

Clause types: deliverable, behavior, exact_output_set, forbidden_output,
performance, external_dependency, presentation, evidence, user_interaction.

Feasibility: executable | provisionable | substitutable | user_waivable |
externally_blocked | contradictory.

The contract is the authoritative definition of done. Model-authored tests
cannot silently add requirements.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

CLAUSE_TYPES = (
    "deliverable",
    "behavior",
    "exact_output_set",
    "forbidden_output",
    "performance",
    "external_dependency",
    "presentation",
    "evidence",
    "user_interaction",
)

HARDNESS = ("hard", "soft", "contradictory", "capability_dependent",
            "externally_dependent", "unverifiable")

FEASIBILITY = (
    "executable",
    "provisionable",
    "substitutable",
    "user_waivable",
    "externally_blocked",
    "contradictory",
)

# Patterns for exact file deliverables
_FILE_EXPLICIT = re.compile(
    r"(?:exactly\s+)?(?:one\s+|a\s+single\s+|single\s+)?"
    r"(?:file\s+)?[`'\"]?([A-Za-z0-9_./\-]+\.(?:html?|py|js|ts|css|json|md|txt|pdf|svg))[`'\"]?",
    re.I,
)
_EXACT_ONE = re.compile(
    r"\b(?:exactly\s+one|only\s+one|a\s+single\s+file|one\s+file\s+only|"
    r"single\s+(?:html|python|js)\s+file|no\s+helper)\b",
    re.I,
)
_EXACT_N = re.compile(r"\bexactly\s+(\d+)\s+files?\b", re.I)
_FORBIDDEN_EXT = re.compile(
    r"\bno\s+\.?(py|js|ts|css|html|pdf|md)\b|\bwithout\s+(?:any\s+)?"
    r"(?:python|javascript|helper|extra)\s+files?\b",
    re.I,
)
_BROWSER_CUES = re.compile(
    r"\b(browser|playable|canvas|animation|keydown|requestAnimationFrame|"
    r"interactive\s+game|html5?\s+game|open\s+in\s+browser|xdg-open)\b",
    re.I,
)
_PDF_CUES = re.compile(r"\b(pdf|reportlab|fpdf|weasyprint|output\.pdf)\b", re.I)
_NETWORK_CUES = re.compile(
    r"\b(http\s+request|fetch\s+url|call\s+api|download|scrape|network)\b", re.I
)
_CONTRADICTION_PAIRS = [
    (re.compile(r"\bno\s+javascript\b", re.I), re.compile(r"\bcanvas\b|\brequestAnimationFrame\b", re.I)),
    (re.compile(r"\bpython\s+only\b|\bonly\s+python\b", re.I), re.compile(r"\bindex\.html\b|\bhtml\s+game\b", re.I)),
    (re.compile(r"\bno\s+files?\b|\bzero\s+files?\b", re.I), re.compile(r"\bwrite\s+(?:a\s+)?file\b|\bcreate\s+.*\.py\b", re.I)),
    (re.compile(r"\bwithout\s+network\b|\boffline\s+only\b", re.I), re.compile(r"\bfetch\s+from\s+https?://|\bcall\s+the\s+api\b", re.I)),
]


@dataclass
class Clause:
    clause_id: str
    clause_type: str
    text: str
    hardness: str = "hard"
    verifier: str = ""  # e.g. "syntax.python", "html.render", "pdf.exists"
    capability_dependency: str = ""  # capability graph node id
    artifact_dependency: str = ""  # path or role
    waiver_policy: str = "none"  # none | user | provision
    feasibility: str = "executable"
    status: str = "open"  # open | green | red | waived | blocked
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Clause":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class CompiledContract:
    source_text: str
    clauses: List[Clause] = field(default_factory=list)
    required_paths: List[str] = field(default_factory=list)
    optional_paths: List[str] = field(default_factory=list)
    forbidden_paths: List[str] = field(default_factory=list)
    forbidden_extensions: List[str] = field(default_factory=list)
    exact_count: Optional[int] = None  # exact deliverable file count
    primary_language: str = ""  # python | html | pdf | unknown
    contradictory: bool = False
    contradictions: List[str] = field(default_factory=list)
    feasibility: str = "executable"
    contract_id: str = ""
    open_hard: int = 0
    green_hard: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["clauses"] = [c.to_dict() if isinstance(c, Clause) else c for c in self.clauses]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CompiledContract":
        d = dict(d or {})
        clauses = [Clause.from_dict(x) if isinstance(x, dict) else x
                   for x in (d.get("clauses") or [])]
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        kwargs = {k: v for k, v in d.items() if k in known and k != "clauses"}
        kwargs["clauses"] = clauses
        return cls(**kwargs)

    def hard_clauses(self) -> List[Clause]:
        return [c for c in self.clauses if c.hardness == "hard"]

    def recompute_counts(self) -> None:
        hard = self.hard_clauses()
        self.open_hard = sum(1 for c in hard if c.status == "open")
        self.green_hard = sum(1 for c in hard if c.status == "green")

    def all_hard_green(self) -> bool:
        hard = self.hard_clauses()
        return bool(hard) and all(c.status in ("green", "waived") for c in hard)


def _cid(prefix: str, text: str) -> str:
    h = hashlib.sha256(f"{prefix}:{text}".encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


def _detect_primary_language(text: str, paths: List[str]) -> str:
    t = (text or "").lower()
    if any(p.endswith((".html", ".htm")) for p in paths) or _BROWSER_CUES.search(text or ""):
        if not any(p.endswith(".py") for p in paths) or "snake" in t or "game" in t:
            return "html"
    if _PDF_CUES.search(text or "") or any(p.endswith(".pdf") for p in paths):
        return "pdf"
    if any(p.endswith(".py") for p in paths) or re.search(r"\bpython\b|\.py\b", t):
        return "python"
    if _BROWSER_CUES.search(text or ""):
        return "html"
    if re.search(r"\b(game|canvas|playable|browser)\b", t):
        return "html"
    return "python" if re.search(r"\b(function|class|implement|script)\b", t) else "unknown"


def compile_contract(user_request: str, *, environment_caps: Optional[Set[str]] = None) -> CompiledContract:
    """Compile freeform user language into a structured contract before mutation."""
    text = user_request or ""
    clauses: List[Clause] = []
    required: List[str] = []
    forbidden_paths: List[str] = []
    forbidden_ext: List[str] = []
    exact_count: Optional[int] = None
    contradictions: List[str] = []
    caps = environment_caps or set()

    # Explicit file mentions
    for m in _FILE_EXPLICIT.finditer(text):
        path = m.group(1)
        if path not in required:
            required.append(path)
            clauses.append(Clause(
                clause_id=_cid("del", path),
                clause_type="deliverable",
                text=f"Deliver file {path}",
                hardness="hard",
                verifier="exists.path",
                artifact_dependency=path,
                feasibility="executable",
            ))

    # Exact-one / exact-N
    m_n = _EXACT_N.search(text)
    if m_n:
        exact_count = int(m_n.group(1))
    elif _EXACT_ONE.search(text):
        exact_count = 1

    if exact_count is not None:
        clauses.append(Clause(
            clause_id=_cid("exact", str(exact_count)),
            clause_type="exact_output_set",
            text=f"Exact deliverable set size = {exact_count}",
            hardness="hard",
            verifier="manifest.exact_count",
            feasibility="executable",
        ))

    # Forbidden extensions / helpers
    for m in _FORBIDDEN_EXT.finditer(text):
        ext = (m.group(1) or "").lower()
        if ext and ext not in forbidden_ext:
            forbidden_ext.append(ext if ext.startswith(".") else f".{ext}")
            clauses.append(Clause(
                clause_id=_cid("forb", ext),
                clause_type="forbidden_output",
                text=f"Forbidden extension .{ext.lstrip('.')}",
                hardness="hard",
                verifier="manifest.forbidden",
                feasibility="executable",
            ))

    if re.search(r"\bno\s+helper\b|\bwithout\s+helper\b|\bonly\s+the\s+requested\s+file\b", text, re.I):
        if exact_count is None:
            exact_count = 1
        clauses.append(Clause(
            clause_id=_cid("forb", "helper"),
            clause_type="forbidden_output",
            text="No helper / undeclared extra files",
            hardness="hard",
            verifier="manifest.no_extra",
            feasibility="executable",
        ))

    primary = _detect_primary_language(text, required)

    # Infer default deliverable when none named
    if not required:
        if primary == "html":
            required.append("index.html")
            clauses.append(Clause(
                clause_id=_cid("del", "index.html"),
                clause_type="deliverable",
                text="Deliver playable index.html",
                hardness="hard",
                verifier="html.render",
                capability_dependency="html.render",
                artifact_dependency="index.html",
                feasibility="executable" if "html.render" in caps or not caps else "provisionable",
            ))
        elif primary == "pdf":
            required.append("output.pdf")
            clauses.append(Clause(
                clause_id=_cid("del", "output.pdf"),
                clause_type="deliverable",
                text="Deliver output.pdf",
                hardness="hard",
                verifier="pdf.exists",
                artifact_dependency="output.pdf",
                feasibility="executable",
            ))
        elif primary == "python":
            # Prefer not to force main.py when HTML is equally plausible —
            # only default to main.py for clearly Python tasks.
            required.append("main.py")
            clauses.append(Clause(
                clause_id=_cid("del", "main.py"),
                clause_type="deliverable",
                text="Deliver main.py",
                hardness="soft",  # soft unless task named it
                verifier="syntax.python",
                artifact_dependency="main.py",
                feasibility="executable",
            ))

    # Browser / visual behavior
    if _BROWSER_CUES.search(text) or primary == "html":
        feasibility = "executable"
        if caps and "html.render" not in caps and "desktop.open" not in caps:
            feasibility = "substitutable"  # static lint / headless alternative
        clauses.append(Clause(
            clause_id=_cid("beh", "browser"),
            clause_type="behavior",
            text="Playable / renderable in browser (not desktop opener)",
            hardness="hard",
            verifier="html.render",
            capability_dependency="html.render",
            feasibility=feasibility,
        ))
        # Negative: desktop open is not a valid verifier in headless jail
        clauses.append(Clause(
            clause_id=_cid("forb", "xdg-open"),
            clause_type="forbidden_output",
            text="Do not use desktop browser openers (xdg-open) as verification",
            hardness="hard",
            verifier="capability.negative",
            capability_dependency="desktop.open",
            feasibility="executable",
        ))

    # PDF existence
    if primary == "pdf" or _PDF_CUES.search(text):
        clauses.append(Clause(
            clause_id=_cid("beh", "pdf"),
            clause_type="evidence",
            text="PDF artifact must exist and be non-empty",
            hardness="hard",
            verifier="pdf.exists",
            feasibility="executable",
        ))

    # Network dependency
    if _NETWORK_CUES.search(text):
        net_ok = "network.outbound" in caps if caps else False
        clauses.append(Clause(
            clause_id=_cid("ext", "network"),
            clause_type="external_dependency",
            text="Outbound network required",
            hardness="capability_dependent",
            capability_dependency="network.outbound",
            feasibility="executable" if net_ok else "externally_blocked",
            waiver_policy="user",
        ))

    # Contradictions
    for a, b in _CONTRADICTION_PAIRS:
        if a.search(text) and b.search(text):
            msg = f"Contradictory requirements: {a.pattern} vs {b.pattern}"
            contradictions.append(msg)
            clauses.append(Clause(
                clause_id=_cid("ctr", msg[:40]),
                clause_type="behavior",
                text=msg,
                hardness="contradictory",
                feasibility="contradictory",
            ))

    # Feasibility aggregate
    contradictory = bool(contradictions) or any(c.hardness == "contradictory" for c in clauses)
    feasibility = "contradictory" if contradictory else "executable"
    if any(c.feasibility == "externally_blocked" for c in clauses):
        feasibility = "externally_blocked" if not contradictory else "contradictory"
    elif any(c.feasibility in ("provisionable", "substitutable") for c in clauses):
        if feasibility == "executable":
            feasibility = "substitutable"

    contract_id = "ctr_" + hashlib.sha256(text.encode()).hexdigest()[:16]
    cc = CompiledContract(
        source_text=text,
        clauses=clauses,
        required_paths=required,
        forbidden_paths=forbidden_paths,
        forbidden_extensions=forbidden_ext,
        exact_count=exact_count,
        primary_language=primary,
        contradictory=contradictory,
        contradictions=contradictions,
        feasibility=feasibility,
        contract_id=contract_id,
    )
    cc.recompute_counts()
    return cc


def check_manifest_against_contract(
    contract: CompiledContract,
    paths: Sequence[str],
    *,
    path_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compare a complete final tree against the compiled contract schema.

    Fail-closed for exact-count, forbidden extensions, and missing required paths.
    """
    files = [p for p in paths if p and not p.endswith("/")]
    file_set = set(files)
    violations: List[str] = []
    notes: List[str] = []

    # Required paths
    for req in contract.required_paths:
        if req not in file_set:
            # soft default main.py is not a hard fail if HTML primary
            soft_ids = {c.clause_id for c in contract.clauses
                        if c.artifact_dependency == req and c.hardness == "soft"}
            if soft_ids and contract.primary_language in ("html", "pdf"):
                notes.append(f"soft deliverable {req} absent (ok for {contract.primary_language})")
            else:
                violations.append(f"missing required path: {req}")
                for c in contract.clauses:
                    if c.artifact_dependency == req and c.hardness == "hard":
                        c.status = "red"
                        c.evidence = "missing"
        else:
            for c in contract.clauses:
                if c.artifact_dependency == req and c.clause_type == "deliverable":
                    c.status = "green"
                    c.evidence = "present"
                    if path_hashes and req in path_hashes:
                        c.evidence = f"present sha256={path_hashes[req][:12]}"

    # Exact count
    if contract.exact_count is not None:
        # Count only non-test, non-hidden deliverables
        deliverables = [p for p in files if not p.startswith(".") and "/__pycache__/" not in p]
        if len(deliverables) != contract.exact_count:
            violations.append(
                f"exact_count={contract.exact_count} but manifest has {len(deliverables)}: "
                + ", ".join(sorted(deliverables)[:12])
            )
            for c in contract.clauses:
                if c.clause_type == "exact_output_set":
                    c.status = "red"
                    c.evidence = f"got {len(deliverables)}"
        else:
            for c in contract.clauses:
                if c.clause_type == "exact_output_set":
                    c.status = "green"
                    c.evidence = f"count={len(deliverables)}"

    # Forbidden extensions
    for p in files:
        for ext in contract.forbidden_extensions:
            if p.lower().endswith(ext if ext.startswith(".") else f".{ext}"):
                violations.append(f"forbidden extension in {p}")
                for c in contract.clauses:
                    if c.clause_type == "forbidden_output":
                        c.status = "red"
                        c.evidence = p

    # Extra files when exact set is implied by required_paths alone
    if contract.exact_count is not None and contract.required_paths:
        extras = [p for p in files if p not in set(contract.required_paths)
                  and not p.startswith(".")]
        if extras and contract.exact_count == len(contract.required_paths):
            for e in extras:
                if e not in violations:
                    violations.append(f"unapproved extra artifact: {e}")
            for c in contract.clauses:
                if c.clause_type in ("exact_output_set", "forbidden_output"):
                    if c.status != "green":
                        c.status = "red"
                        c.evidence = f"extras={extras[:5]}"

    contract.recompute_counts()
    ok = not violations and not contract.contradictory
    return {
        "ok": ok,
        "violations": violations,
        "notes": notes,
        "paths": list(files),
        "exact_count": contract.exact_count,
        "required_paths": list(contract.required_paths),
        "contract_id": contract.contract_id,
        "open_hard": contract.open_hard,
        "green_hard": contract.green_hard,
        "contradictory": contract.contradictory,
    }
