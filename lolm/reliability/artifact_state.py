# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Typed Artifact State Machine (TASM).

States: proposed → written → syntax-valid → execution-valid → contract-valid →
checkpointed → superseded | rejected | delivered.

HTML cannot be py_compile input; PDF cannot be treated as text without a PDF
validator; a helper file cannot enter an exact-one deliverable set.
"""

from __future__ import annotations

import hashlib
import mimetypes
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

ARTIFACT_STATES = (
    "proposed",
    "written",
    "syntax_valid",
    "execution_valid",
    "contract_valid",
    "checkpointed",
    "superseded",
    "rejected",
    "delivered",
)

# Validators accept only these language/mime families
VALIDATOR_TYPES: Dict[str, Set[str]] = {
    "syntax.python": {"python", "text/x-python"},
    "unittest": {"python", "text/x-python"},
    "pytest": {"python", "text/x-python"},
    "html.render": {"html", "text/html"},
    "html.static_lint": {"html", "text/html"},
    "pdf.exists": {"pdf", "application/pdf"},
    "pdf.validate": {"pdf", "application/pdf"},
    "exists.path": set(),  # any
    "manifest.exact_count": set(),
    "manifest.forbidden": set(),
    "manifest.no_extra": set(),
}

_EXT_LANG = {
    ".py": ("python", "text/x-python"),
    ".html": ("html", "text/html"),
    ".htm": ("html", "text/html"),
    ".js": ("javascript", "text/javascript"),
    ".ts": ("typescript", "text/typescript"),
    ".css": ("css", "text/css"),
    ".json": ("json", "application/json"),
    ".md": ("markdown", "text/markdown"),
    ".txt": ("text", "text/plain"),
    ".pdf": ("pdf", "application/pdf"),
    ".svg": ("svg", "image/svg+xml"),
}


def infer_language(path: str, content: Optional[str] = None) -> tuple:
    """Return (language, mime). Extension is evidence, not sole truth."""
    p = (path or "").lower()
    for ext, pair in _EXT_LANG.items():
        if p.endswith(ext):
            return pair
    if content:
        head = content.lstrip()[:200].lower()
        if head.startswith("<!doctype html") or head.startswith("<html"):
            return ("html", "text/html")
        if "%pdf" in head[:20]:
            return ("pdf", "application/pdf")
        if "def " in head or "import " in head:
            return ("python", "text/x-python")
    mime, _ = mimetypes.guess_type(path or "")
    return ("unknown", mime or "application/octet-stream")


def validator_accepts(validator: str, language: str, mime: str = "") -> bool:
    accepted = VALIDATOR_TYPES.get(validator)
    if accepted is None:
        return True  # unknown validator — do not block
    if not accepted:
        return True  # any-type validators
    return language in accepted or mime in accepted


@dataclass
class ArtifactRecord:
    artifact_id: str
    path: str
    role: str = "deliverable"  # deliverable | helper | test | intermediate | forbidden
    language_or_mime: str = "unknown"
    mime: str = "application/octet-stream"
    contract_clause_ids: List[str] = field(default_factory=list)
    source_candidate_id: str = ""
    created_at_step: int = 0
    content_sha256: str = ""
    validators_required: List[str] = field(default_factory=list)
    validators_run: List[str] = field(default_factory=list)
    verifier_evidence_ids: List[str] = field(default_factory=list)
    checkpoint_id: str = ""
    delivery_status: str = "proposed"
    supersedes: str = ""
    size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArtifactRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


def _aid(path: str, sha: str) -> str:
    return "art_" + hashlib.sha256(f"{path}:{sha}".encode()).hexdigest()[:16]


class ArtifactRegistry:
    """Typed registry of workspace artifacts with lifecycle transitions."""

    def __init__(self) -> None:
        self.records: Dict[str, ArtifactRecord] = {}  # path -> record
        self._history: List[Dict[str, Any]] = []

    def upsert(
        self,
        path: str,
        content: str | bytes,
        *,
        step: int = 0,
        role: str = "deliverable",
        clause_ids: Optional[Sequence[str]] = None,
        validators_required: Optional[Sequence[str]] = None,
        source_candidate_id: str = "",
    ) -> ArtifactRecord:
        if isinstance(content, bytes):
            body = content
            text = None
        else:
            text = content
            body = content.encode("utf-8", errors="replace")
        sha = hashlib.sha256(body).hexdigest()
        lang, mime = infer_language(path, text if text is not None else None)
        prev = self.records.get(path)
        if prev and prev.content_sha256 and prev.content_sha256 != sha:
            prev.delivery_status = "superseded"
            self._history.append({"event": "supersede", "path": path, "old": prev.artifact_id})
        rec = ArtifactRecord(
            artifact_id=_aid(path, sha),
            path=path,
            role=role,
            language_or_mime=lang,
            mime=mime,
            contract_clause_ids=list(clause_ids or (prev.contract_clause_ids if prev else [])),
            source_candidate_id=source_candidate_id,
            created_at_step=step,
            content_sha256=sha,
            validators_required=list(validators_required or (prev.validators_required if prev else [])),
            validators_run=[],
            delivery_status="written",
            supersedes=prev.artifact_id if prev else "",
            size=len(body),
        )
        # Type change invalidates prior verifier evidence
        if prev and (prev.language_or_mime != lang or prev.mime != mime):
            self._history.append({
                "event": "type_migration",
                "path": path,
                "from": prev.language_or_mime,
                "to": lang,
            })
        self.records[path] = rec
        return rec

    def mark_validator(
        self,
        path: str,
        validator: str,
        *,
        ok: bool,
        evidence_id: str = "",
    ) -> Optional[str]:
        """Run a typed validator transition. Returns error if type-incompatible."""
        rec = self.records.get(path)
        if rec is None:
            return f"unknown artifact path: {path}"
        if not validator_accepts(validator, rec.language_or_mime, rec.mime):
            return (
                f"validator {validator} incompatible with {path} "
                f"(language={rec.language_or_mime}, mime={rec.mime})"
            )
        if validator not in rec.validators_run:
            rec.validators_run.append(validator)
        if evidence_id:
            rec.verifier_evidence_ids.append(evidence_id)
        if ok:
            if validator.startswith("syntax.") and rec.delivery_status == "written":
                rec.delivery_status = "syntax_valid"
            elif validator in ("unittest", "pytest", "html.render", "pdf.exists"):
                if rec.delivery_status in ("written", "syntax_valid"):
                    rec.delivery_status = "execution_valid"
        return None

    def mark_contract_valid(self, paths: Sequence[str]) -> None:
        for p in paths:
            rec = self.records.get(p)
            if rec and rec.delivery_status in (
                "written", "syntax_valid", "execution_valid"
            ):
                rec.delivery_status = "contract_valid"

    def mark_checkpointed(self, paths: Sequence[str], checkpoint_id: str) -> None:
        for p in paths:
            rec = self.records.get(p)
            if rec:
                rec.checkpoint_id = checkpoint_id
                rec.delivery_status = "checkpointed"

    def mark_delivered(self, paths: Sequence[str]) -> None:
        for p in paths:
            rec = self.records.get(p)
            if rec:
                rec.delivery_status = "delivered"

    def mark_rejected(self, path: str, reason: str = "") -> None:
        rec = self.records.get(path)
        if rec:
            rec.delivery_status = "rejected"
            self._history.append({"event": "reject", "path": path, "reason": reason})

    def tree_hashes(self) -> Dict[str, str]:
        return {p: r.content_sha256 for p, r in sorted(self.records.items())
                if r.delivery_status not in ("rejected", "superseded")}

    def active_paths(self) -> List[str]:
        return [p for p, r in self.records.items()
                if r.delivery_status not in ("rejected", "superseded")]

    def type_safe_validators(self, path: str) -> List[str]:
        rec = self.records.get(path)
        if not rec:
            return []
        return [v for v, accepted in VALIDATOR_TYPES.items()
                if not accepted or rec.language_or_mime in accepted or rec.mime in accepted]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": {k: v.to_dict() for k, v in self.records.items()},
            "history": list(self._history[-100:]),
        }
