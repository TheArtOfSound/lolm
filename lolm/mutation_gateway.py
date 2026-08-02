# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Mandatory repository mutation gateway.

All repository-changing operations must go through this service. Blind edits,
stale-revision writes, unauthorized creates, and path escapes are rejected
deterministically. Prompt instructions never authorize mutations.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from lolm.repo_context import (
    ReadBeforeEditGuard,
    RepositoryMap,
    SourceDocument,
    build_repository_map,
    content_hash,
    detect_language,
    rank_repository_context,
)


class MutationOp(str, Enum):
    CREATE = "create"
    EDIT = "edit"                 # search-replace or partial
    RANGE_EDIT = "range_edit"
    SYMBOL_EDIT = "symbol_edit"
    FULL_REWRITE = "full_rewrite"
    DELETE = "delete"
    RENAME = "rename"


class MutationState(str, Enum):
    READ = "read"
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    APPLIED = "applied"
    VERIFIED = "verified"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


_BINARY_HINT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_UNSAFE_PATH = re.compile(r"(^|/)\.\.(/|$)|^/|\\\\|[\x00]")


def normalize_repo_path(path: str) -> str:
    """Jail-safe relative path (posix). Rejects escapes and absolute paths."""
    raw = (path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or _UNSAFE_PATH.search(raw):
        raise ValueError(f"path rejected: {path!r}")
    # Collapse dots via PurePosixPath; reject if escapes root
    parts = []
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"path escape rejected: {path!r}")
        parts.append(part)
    if not parts:
        raise ValueError(f"empty path rejected: {path!r}")
    return "/".join(parts)


def _mid(prefix: str = "mut") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class ReadAuthorization:
    path: str
    sha256: str
    size: int
    revision: int
    scope: str  # full | range | symbol
    step: int
    symbols: Tuple[str, ...] = field(default_factory=tuple)
    line_start: int = 0
    line_end: int = 0
    content_sample: str = ""  # optional excerpt for range scope

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "revision": self.revision,
            "scope": self.scope,
            "step": self.step,
            "symbols": list(self.symbols),
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


@dataclass
class MutationProposal:
    mutation_id: str
    path: str
    operation: MutationOp
    new_content: str = ""
    old_fragment: str = ""
    rename_to: str = ""
    read_sha256: str = ""
    read_size: int = 0
    read_revision: int = 0
    selected_symbols: Tuple[str, ...] = field(default_factory=tuple)
    selection_reason: str = ""
    patch_id: str = ""
    step: int = 0
    requires_full_read: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["operation"] = self.operation.value
        d["selected_symbols"] = list(self.selected_symbols)
        # Do not dump full content into logs by default
        if len(self.new_content) > 200:
            d["new_content"] = f"<omitted len={len(self.new_content)}>"
        return d


@dataclass
class MutationRecord:
    mutation_id: str
    path: str
    operation: str
    state: str
    selection_reason: str = ""
    read_before_edit: bool = False
    read_sha256: str = ""
    pre_apply_sha256: str = ""
    post_apply_sha256: str = ""
    compare_and_swap_passed: bool = False
    accepted: bool = False
    rollback: bool = False
    rejection_reason: str = ""
    verification: Dict[str, Any] = field(default_factory=dict)
    selected_symbols: List[str] = field(default_factory=list)
    step: int = 0
    ts: float = 0.0
    # Pre-image for rollback
    prior_content: Optional[str] = None
    prior_existed: bool = False
    created_path: str = ""  # for create/rename

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("prior_content", None)  # keep receipts lean; hash is enough
        return d


@dataclass
class MapEntry:
    path: str
    language: str
    sha256: str
    symbols: List[str]
    imports: List[str]
    references: List[str]
    test_links: List[str]
    revision: int
    last_read_step: int
    last_modified_step: int

    def to_dict(self) -> dict:
        return asdict(self)


class MutationGateway:
    """Single mandatory gateway for repository mutations."""

    def __init__(
        self,
        sandbox: Any,
        *,
        task: str = "",
        primary_language: str = "",
        required_paths: Optional[Sequence[str]] = None,
        exact_count: Optional[int] = None,
        forbidden_extensions: Optional[Sequence[str]] = None,
        allow_python_helpers: bool = True,
        step: int = 0,
    ) -> None:
        self.sb = sandbox
        self.task = task or ""
        self.primary_language = (primary_language or "").lower()
        self.required_paths = list(required_paths or [])
        self.exact_count = exact_count
        self.forbidden_extensions = list(forbidden_extensions or [])
        self.allow_python_helpers = allow_python_helpers
        self.step = step
        self.guard = ReadBeforeEditGuard()
        self._reads: Dict[str, ReadAuthorization] = {}
        self._revisions: Dict[str, int] = {}
        self._map_entries: Dict[str, MapEntry] = {}
        self.mutations: List[MutationRecord] = []
        self._pending: Dict[str, MutationProposal] = {}
        self._selection_cache: List[Dict[str, Any]] = []
        self.repo_map: Optional[RepositoryMap] = None

    # ── inventory / selection ─────────────────────────────────────────────

    def inventory(self) -> List[str]:
        try:
            return list(self.sb.list_files(limit=500))
        except Exception:
            return []

    def _load_documents(self) -> List[SourceDocument]:
        docs: List[SourceDocument] = []
        for path in self.inventory():
            try:
                content = self.sb.read_file(path)
            except Exception:
                continue
            if content is None:
                continue
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8")
                except Exception:
                    continue
            docs.append(SourceDocument(path=path, content=str(content)))
        return docs

    def refresh_map(self, *, step: Optional[int] = None) -> RepositoryMap:
        if step is not None:
            self.step = step
        docs = self._load_documents()
        self.repo_map = build_repository_map(docs)
        for file in self.repo_map.files:
            rev = self._revisions.get(file.path, 0)
            prev = self._map_entries.get(file.path)
            self._map_entries[file.path] = MapEntry(
                path=file.path,
                language=file.language,
                sha256=file.content_hash,
                symbols=[s.name for s in file.symbols],
                imports=list(file.imports),
                references=list(file.references),
                test_links=[
                    p for p in self.inventory()
                    if "test" in p.lower() and file.path.rsplit(".", 1)[0] in p
                ],
                revision=rev,
                last_read_step=prev.last_read_step if prev else 0,
                last_modified_step=prev.last_modified_step if prev else 0,
            )
        return self.repo_map

    def select_targets(
        self,
        query: str,
        *,
        failing_paths: Optional[Sequence[str]] = None,
        stack_paths: Optional[Sequence[str]] = None,
        token_budget: int = 4000,
        max_files: int = 12,
    ) -> List[Dict[str, Any]]:
        docs = self._load_documents()
        if self.repo_map is None:
            self.refresh_map()
        failing = list(failing_paths or []) + list(stack_paths or [])
        selection = rank_repository_context(
            query or self.task,
            docs,
            self.repo_map,
            failing_paths=failing,
            token_budget=token_budget,
            max_files=max_files,
        )
        # Language compatibility boost/filter note
        out: List[Dict[str, Any]] = []
        for item in selection.items:
            reasons = list(item.reason)
            lang = detect_language(item.path)
            if self.primary_language and self.primary_language != "unknown":
                if self.primary_language == "html" and lang == "python":
                    reasons.append("language_mismatch_python_on_html_task")
                elif self.primary_language == lang:
                    reasons.append("language_match")
            out.append({
                "path": item.path,
                "score": item.score,
                "reason": reasons,
                "symbols": list(item.symbols),
                "estimated_tokens": item.estimated_tokens,
                "excerpt": item.excerpt[:500],
            })
        self._selection_cache = out
        return out

    # ── read ──────────────────────────────────────────────────────────────

    def read(
        self,
        path: str,
        *,
        scope: str = "full",
        step: Optional[int] = None,
        symbols: Optional[Sequence[str]] = None,
        line_start: int = 0,
        line_end: int = 0,
    ) -> Tuple[str, ReadAuthorization]:
        path = normalize_repo_path(path)
        if step is not None:
            self.step = step
        try:
            content = self.sb.read_file(path)
        except Exception as exc:
            raise FileNotFoundError(f"cannot read {path}: {exc}") from exc
        if content is None:
            raise FileNotFoundError(path)
        if isinstance(content, bytes):
            if b"\x00" in content[:1024]:
                raise ValueError(f"binary file rejected: {path}")
            content = content.decode("utf-8", errors="replace")
        text = str(content)
        digest = self.guard.record_read(path, text)
        rev = self._revisions.get(path, 0)
        auth = ReadAuthorization(
            path=path,
            sha256=digest,
            size=len(text.encode("utf-8", errors="replace")),
            revision=rev,
            scope=scope if scope in ("full", "range", "symbol") else "full",
            step=self.step,
            symbols=tuple(symbols or ()),
            line_start=line_start,
            line_end=line_end,
            content_sample=text[:400] if scope != "full" else "",
        )
        self._reads[path] = auth
        if path in self._map_entries:
            e = self._map_entries[path]
            self._map_entries[path] = MapEntry(
                **{**e.to_dict(), "last_read_step": self.step, "sha256": digest}
            )
        rec = MutationRecord(
            mutation_id=_mid("read"),
            path=path,
            operation="read",
            state=MutationState.READ.value,
            read_before_edit=True,
            read_sha256=digest,
            step=self.step,
            ts=time.time(),
            selected_symbols=list(symbols or ()),
        )
        self.mutations.append(rec)
        return text, auth

    # ── authorize create ──────────────────────────────────────────────────

    def authorize_create(
        self,
        path: str,
        content: str,
        *,
        selection_reason: str = "",
        step: Optional[int] = None,
    ) -> MutationProposal:
        path = normalize_repo_path(path)
        if step is not None:
            self.step = step
        # Collision
        try:
            existing = self.sb.read_file(path)
            if existing is not None:
                raise PermissionError(f"create rejected: {path} already exists")
        except FileNotFoundError:
            pass
        except PermissionError:
            raise
        except Exception:
            pass  # missing is ok

        lang = detect_language(path, "")
        # HTML-only task: block new python product files
        if self.primary_language == "html" and lang == "python":
            name = PurePosixPath(path).name
            if not (name.startswith("test_") or name.endswith("_test.py")):
                raise PermissionError(
                    f"create rejected: Python product file {path} on HTML-primary task"
                )
        # Forbidden extensions
        for ext in self.forbidden_extensions:
            e = ext if ext.startswith(".") else f".{ext}"
            if path.lower().endswith(e):
                raise PermissionError(f"create rejected: forbidden extension {e}")
        # Exact-count / manifest
        if self.exact_count is not None:
            current = [p for p in self.inventory() if not p.startswith(".")]
            if path not in current and len(current) + 1 > self.exact_count:
                if path not in self.required_paths:
                    raise PermissionError(
                        f"create rejected: exact_count={self.exact_count} already at capacity"
                    )
        # Duplicate implementation: same basename elsewhere
        base = PurePosixPath(path).name
        for existing in self.inventory():
            if PurePosixPath(existing).name == base and existing != path:
                # Allow tests/ mirror
                if "test" not in existing.lower() and "test" not in path.lower():
                    raise PermissionError(
                        f"create rejected: duplicates existing {existing}"
                    )
        # Binary reject
        if _BINARY_HINT.search(content or ""):
            raise PermissionError(f"create rejected: binary content for {path}")

        prop = MutationProposal(
            mutation_id=_mid(),
            path=path,
            operation=MutationOp.CREATE,
            new_content=content or "",
            selection_reason=selection_reason or "task_authorized_create",
            patch_id=_mid("patch"),
            step=self.step,
        )
        self._pending[prop.mutation_id] = prop
        return prop

    # ── authorize edit ────────────────────────────────────────────────────

    def authorize_edit(
        self,
        path: str,
        new_content: str,
        *,
        operation: MutationOp = MutationOp.FULL_REWRITE,
        old_fragment: str = "",
        selection_reason: str = "",
        selected_symbols: Optional[Sequence[str]] = None,
        step: Optional[int] = None,
    ) -> MutationProposal:
        path = normalize_repo_path(path)
        if step is not None:
            self.step = step
        # Current content for CAS
        try:
            current = self.sb.read_file(path)
            if isinstance(current, bytes):
                if b"\x00" in current[:1024]:
                    raise PermissionError(f"binary edit rejected: {path}")
                current = current.decode("utf-8", errors="replace")
            current = str(current or "")
        except Exception as exc:
            raise FileNotFoundError(f"edit target missing: {path}: {exc}") from exc

        decision = self.guard.decide(path, current, creating=False)
        if not decision.allowed:
            raise PermissionError(
                f"edit rejected for {path}: {decision.reason}"
            )

        auth = self._reads.get(path)
        # Scope check: full rewrite requires full read
        if operation == MutationOp.FULL_REWRITE:
            if auth is None or auth.scope != "full":
                # Allow if recorded read was full content (default scope full)
                if auth is None:
                    raise PermissionError(
                        f"full rewrite rejected: no read of {path}"
                    )
                if auth.scope in ("range", "symbol") and len(new_content) > max(
                    auth.size * 2, auth.size + 500
                ):
                    raise PermissionError(
                        f"full rewrite rejected: read scope was {auth.scope}"
                    )

        # Must not write different path than read without explicit authorize
        # (path is already bound)

        if _BINARY_HINT.search(new_content or ""):
            raise PermissionError(f"edit rejected: binary content for {path}")

        prop = MutationProposal(
            mutation_id=_mid(),
            path=path,
            operation=operation,
            new_content=new_content or "",
            old_fragment=old_fragment or "",
            read_sha256=decision.expected_hash,
            read_size=auth.size if auth else len(current.encode("utf-8")),
            read_revision=auth.revision if auth else self._revisions.get(path, 0),
            selected_symbols=tuple(selected_symbols or (auth.symbols if auth else ())),
            selection_reason=selection_reason or "authorized_edit",
            patch_id=_mid("patch"),
            step=self.step,
            requires_full_read=(operation == MutationOp.FULL_REWRITE),
        )
        self._pending[prop.mutation_id] = prop
        return prop

    def authorize_delete(
        self,
        path: str,
        *,
        selection_reason: str = "",
        step: Optional[int] = None,
    ) -> MutationProposal:
        path = normalize_repo_path(path)
        if step is not None:
            self.step = step
        try:
            current = self.sb.read_file(path) or ""
        except Exception as exc:
            raise FileNotFoundError(f"delete target missing: {path}") from exc
        if isinstance(current, bytes):
            current = current.decode("utf-8", errors="replace")
        decision = self.guard.decide(path, str(current), creating=False)
        if not decision.allowed:
            raise PermissionError(f"delete rejected for {path}: {decision.reason}")
        prop = MutationProposal(
            mutation_id=_mid(),
            path=path,
            operation=MutationOp.DELETE,
            read_sha256=decision.expected_hash,
            read_revision=self._reads[path].revision if path in self._reads else 0,
            selection_reason=selection_reason or "authorized_delete",
            patch_id=_mid("patch"),
            step=self.step,
        )
        self._pending[prop.mutation_id] = prop
        return prop

    def authorize_rename(
        self,
        path: str,
        new_path: str,
        *,
        selection_reason: str = "",
        step: Optional[int] = None,
    ) -> MutationProposal:
        path = normalize_repo_path(path)
        new_path = normalize_repo_path(new_path)
        if step is not None:
            self.step = step
        content, _ = self.read(path, scope="full", step=self.step)
        # Create target + delete source as one logical rename after authorize both
        prop = MutationProposal(
            mutation_id=_mid(),
            path=path,
            operation=MutationOp.RENAME,
            new_content=content,
            rename_to=new_path,
            read_sha256=self._reads[path].sha256,
            read_revision=self._reads[path].revision,
            selection_reason=selection_reason or "authorized_rename",
            patch_id=_mid("patch"),
            step=self.step,
        )
        self._pending[prop.mutation_id] = prop
        return prop

    # ── apply (CAS) ───────────────────────────────────────────────────────

    def apply(self, proposal: MutationProposal) -> MutationRecord:
        if proposal.mutation_id not in self._pending and proposal.mutation_id not in {
            m.mutation_id for m in self.mutations
        }:
            # Allow applying the object we just authorized
            self._pending[proposal.mutation_id] = proposal

        path = proposal.path
        rec = MutationRecord(
            mutation_id=proposal.mutation_id,
            path=path,
            operation=proposal.operation.value,
            state=MutationState.PROPOSED.value,
            selection_reason=proposal.selection_reason,
            read_before_edit=bool(proposal.read_sha256) or proposal.operation == MutationOp.CREATE,
            read_sha256=proposal.read_sha256,
            selected_symbols=list(proposal.selected_symbols),
            step=proposal.step or self.step,
            ts=time.time(),
        )

        try:
            if proposal.operation == MutationOp.CREATE:
                # CAS: ensure still missing
                try:
                    exists = self.sb.read_file(path)
                    if exists is not None:
                        rec.state = MutationState.REJECTED.value
                        rec.rejection_reason = "create_collision_pre_apply"
                        self.mutations.append(rec)
                        return rec
                except Exception:
                    pass
                rec.prior_existed = False
                rec.prior_content = None
                self.sb.write_file(path, proposal.new_content, reason="gateway_create")
                rec.pre_apply_sha256 = ""
                rec.post_apply_sha256 = content_hash(proposal.new_content)
                rec.compare_and_swap_passed = True
                rec.state = MutationState.APPLIED.value
                rec.created_path = path
                self._bump_revision(path, proposal.new_content)
                self.guard.record_read(path, proposal.new_content)
                self._reads[path] = ReadAuthorization(
                    path=path,
                    sha256=rec.post_apply_sha256,
                    size=len(proposal.new_content.encode("utf-8")),
                    revision=self._revisions[path],
                    scope="full",
                    step=self.step,
                )

            elif proposal.operation == MutationOp.DELETE:
                current = self.sb.read_file(path) or ""
                if isinstance(current, bytes):
                    current = current.decode("utf-8", errors="replace")
                current = str(current)
                pre = content_hash(current)
                rec.pre_apply_sha256 = pre
                if proposal.read_sha256 and pre != proposal.read_sha256:
                    rec.state = MutationState.REJECTED.value
                    rec.rejection_reason = "stale_revision"
                    rec.compare_and_swap_passed = False
                    self.guard.invalidate(path)
                    self.mutations.append(rec)
                    return rec
                rec.prior_content = current
                rec.prior_existed = True
                if hasattr(self.sb, "delete_file"):
                    self.sb.delete_file(path)
                else:
                    # fallback: empty write then delete attempt
                    self.sb.write_file(path, "", reason="gateway_delete_clear")
                rec.compare_and_swap_passed = True
                rec.post_apply_sha256 = ""
                rec.state = MutationState.APPLIED.value
                self.guard.invalidate(path)
                self._reads.pop(path, None)
                self._map_entries.pop(path, None)

            elif proposal.operation == MutationOp.RENAME:
                current = self.sb.read_file(path) or ""
                if isinstance(current, bytes):
                    current = current.decode("utf-8", errors="replace")
                current = str(current)
                pre = content_hash(current)
                rec.pre_apply_sha256 = pre
                if proposal.read_sha256 and pre != proposal.read_sha256:
                    rec.state = MutationState.REJECTED.value
                    rec.rejection_reason = "stale_revision"
                    rec.compare_and_swap_passed = False
                    self.guard.invalidate(path)
                    self.mutations.append(rec)
                    return rec
                dest = proposal.rename_to
                try:
                    if self.sb.read_file(dest) is not None:
                        rec.state = MutationState.REJECTED.value
                        rec.rejection_reason = "rename_destination_exists"
                        self.mutations.append(rec)
                        return rec
                except Exception:
                    pass
                rec.prior_content = current
                rec.prior_existed = True
                self.sb.write_file(dest, current, reason="gateway_rename_create")
                if hasattr(self.sb, "delete_file"):
                    self.sb.delete_file(path)
                rec.compare_and_swap_passed = True
                rec.post_apply_sha256 = content_hash(current)
                rec.state = MutationState.APPLIED.value
                rec.created_path = dest
                self.guard.invalidate(path)
                self._reads.pop(path, None)
                self._bump_revision(dest, current)
                self.guard.record_read(dest, current)

            else:
                # EDIT / FULL_REWRITE / RANGE / SYMBOL
                current = self.sb.read_file(path) or ""
                if isinstance(current, bytes):
                    current = current.decode("utf-8", errors="replace")
                current = str(current)
                pre = content_hash(current)
                rec.pre_apply_sha256 = pre
                if not proposal.read_sha256:
                    rec.state = MutationState.REJECTED.value
                    rec.rejection_reason = "read_required_before_edit"
                    self.mutations.append(rec)
                    return rec
                if pre != proposal.read_sha256:
                    rec.state = MutationState.REJECTED.value
                    rec.rejection_reason = "stale_revision"
                    rec.compare_and_swap_passed = False
                    self.guard.invalidate(path)
                    self.mutations.append(rec)
                    return rec
                new_content = proposal.new_content
                if proposal.operation == MutationOp.EDIT and proposal.old_fragment:
                    if proposal.old_fragment not in current:
                        rec.state = MutationState.REJECTED.value
                        rec.rejection_reason = "old_fragment_not_found"
                        self.mutations.append(rec)
                        return rec
                    new_content = current.replace(proposal.old_fragment, proposal.new_content, 1)
                rec.prior_content = current
                rec.prior_existed = True
                self.sb.write_file(path, new_content, reason="gateway_edit")
                rec.post_apply_sha256 = content_hash(new_content)
                rec.compare_and_swap_passed = True
                rec.state = MutationState.APPLIED.value
                self._bump_revision(path, new_content)
                self.guard.record_read(path, new_content)
                self._reads[path] = ReadAuthorization(
                    path=path,
                    sha256=rec.post_apply_sha256,
                    size=len(new_content.encode("utf-8")),
                    revision=self._revisions[path],
                    scope="full",
                    step=self.step,
                )

            self._pending.pop(proposal.mutation_id, None)
            self.refresh_map(step=self.step)
            if path in self._map_entries:
                e = self._map_entries[path]
                self._map_entries[path] = MapEntry(
                    **{**e.to_dict(), "last_modified_step": self.step}
                )
        except PermissionError as exc:
            rec.state = MutationState.REJECTED.value
            rec.rejection_reason = str(exc)[:200]
        except Exception as exc:
            rec.state = MutationState.REJECTED.value
            rec.rejection_reason = f"apply_error: {exc}"[:200]

        self.mutations.append(rec)
        return rec

    def _bump_revision(self, path: str, content: str) -> None:
        self._revisions[path] = self._revisions.get(path, 0) + 1

    # ── verify / accept / rollback ────────────────────────────────────────

    def record_verification(
        self,
        mutation_id: str,
        *,
        validator: str,
        command: str,
        exit_code: int,
        accepted: bool,
    ) -> Optional[MutationRecord]:
        for rec in reversed(self.mutations):
            if rec.mutation_id == mutation_id:
                rec.verification = {
                    "validator": validator,
                    "command": command,
                    "exit_code": exit_code,
                }
                if accepted and rec.state == MutationState.APPLIED.value:
                    rec.state = MutationState.ACCEPTED.value
                    rec.accepted = True
                elif not accepted and rec.state == MutationState.APPLIED.value:
                    rec.state = MutationState.VERIFIED.value  # verified-failed
                    rec.accepted = False
                return rec
        return None

    def rollback(self, mutation_id: str) -> Optional[MutationRecord]:
        for rec in reversed(self.mutations):
            if rec.mutation_id != mutation_id:
                continue
            if rec.state not in (
                MutationState.APPLIED.value,
                MutationState.VERIFIED.value,
                MutationState.ACCEPTED.value,
            ):
                return rec
            try:
                if rec.operation == MutationOp.CREATE.value or (
                    rec.operation == MutationOp.RENAME.value and rec.created_path
                ):
                    # Remove created path
                    target = rec.created_path or rec.path
                    if hasattr(self.sb, "delete_file"):
                        self.sb.delete_file(target)
                    if rec.operation == MutationOp.RENAME.value and rec.prior_content is not None:
                        self.sb.write_file(rec.path, rec.prior_content, reason="gateway_rollback")
                        self.guard.record_read(rec.path, rec.prior_content)
                elif rec.prior_content is not None:
                    self.sb.write_file(rec.path, rec.prior_content, reason="gateway_rollback")
                    self.guard.record_read(rec.path, rec.prior_content)
                elif rec.operation == MutationOp.DELETE.value and rec.prior_content is not None:
                    self.sb.write_file(rec.path, rec.prior_content, reason="gateway_rollback")
                rec.state = MutationState.ROLLED_BACK.value
                rec.rollback = True
                rec.accepted = False
                self.refresh_map(step=self.step)
            except Exception as exc:
                rec.rejection_reason = f"rollback_failed: {exc}"[:200]
            return rec
        return None

    def rollback_last_applied(self) -> Optional[MutationRecord]:
        for rec in reversed(self.mutations):
            if rec.state in (
                MutationState.APPLIED.value,
                MutationState.VERIFIED.value,
                MutationState.ACCEPTED.value,
            ):
                return self.rollback(rec.mutation_id)
        return None

    # ── high-level helpers used by CodeAgent ──────────────────────────────

    def write(
        self,
        path: str,
        content: str,
        *,
        creating: Optional[bool] = None,
        operation: Optional[MutationOp] = None,
        selection_reason: str = "",
        step: Optional[int] = None,
        old_fragment: str = "",
    ) -> MutationRecord:
        """Authorize + apply in one call (preferred API for the coding loop)."""
        path = normalize_repo_path(path)
        if step is not None:
            self.step = step
        exists = False
        try:
            cur = self.sb.read_file(path)
            exists = cur is not None
        except Exception:
            exists = False

        if creating is True or (creating is None and not exists):
            prop = self.authorize_create(
                path, content, selection_reason=selection_reason, step=self.step,
            )
        else:
            op = operation or (
                MutationOp.EDIT if old_fragment else MutationOp.FULL_REWRITE
            )
            prop = self.authorize_edit(
                path,
                content,
                operation=op,
                old_fragment=old_fragment,
                selection_reason=selection_reason,
                step=self.step,
            )
        return self.apply(prop)

    def receipt_blob(self) -> Dict[str, Any]:
        return {
            "mutation_gateway": {
                "schema": "lolm.mutation_gateway.v1",
                "primary_language": self.primary_language,
                "selection": self._selection_cache[:12],
                "map": {k: v.to_dict() for k, v in list(self._map_entries.items())[:40]},
                "mutations": [m.to_dict() for m in self.mutations[-40:]],
                "reads": {k: v.to_dict() for k, v in self._reads.items()},
            }
        }

    def assert_no_blind_existing_edits(self) -> bool:
        """True if every applied edit/create/delete satisfied RBE/CAS rules."""
        for m in self.mutations:
            if m.state in (MutationState.APPLIED.value, MutationState.ACCEPTED.value):
                if m.operation in (
                    MutationOp.EDIT.value,
                    MutationOp.FULL_REWRITE.value,
                    MutationOp.RANGE_EDIT.value,
                    MutationOp.SYMBOL_EDIT.value,
                    MutationOp.DELETE.value,
                ):
                    if not m.read_before_edit or not m.compare_and_swap_passed:
                        return False
                if m.operation == MutationOp.CREATE.value and not m.compare_and_swap_passed:
                    return False
        return True
