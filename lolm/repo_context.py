# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Repository intelligence for LOLM coding agents.

Large-repository failures are usually context-selection failures before they are
code-generation failures. This module builds a compact symbol/reference map,
ranks relevant files and definitions for a task, and enforces read-before-edit
using content hashes.

Python parsing uses the standard AST. Other languages use a conservative regex
fallback so the interface works without optional dependencies. A production
Tree-sitter backend can replace `extract_symbols` without changing the map,
ranking, or edit-guard contracts.
"""

from __future__ import annotations

import ast
import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class SourceDocument:
    path: str
    content: str
    language: str = ""


@dataclass(frozen=True)
class SymbolRecord:
    path: str
    name: str
    kind: str
    signature: str
    line_start: int
    line_end: int
    references: Tuple[str, ...] = field(default_factory=tuple)
    exported: bool = False

    @property
    def qualified_name(self) -> str:
        return f"{self.path}:{self.name}"


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    symbols: Tuple[SymbolRecord, ...]
    imports: Tuple[str, ...]
    references: Tuple[str, ...]
    content_hash: str
    line_count: int


@dataclass(frozen=True)
class RepositoryMap:
    files: Tuple[FileRecord, ...]
    symbol_index: Mapping[str, Tuple[SymbolRecord, ...]]
    incoming_references: Mapping[str, int]

    def file(self, path: str) -> Optional[FileRecord]:
        return next((item for item in self.files if item.path == path), None)


@dataclass(frozen=True)
class ContextItem:
    path: str
    score: float
    reason: Tuple[str, ...]
    excerpt: str
    estimated_tokens: int
    symbols: Tuple[str, ...]


@dataclass(frozen=True)
class ContextSelection:
    items: Tuple[ContextItem, ...]
    used_tokens: int
    budget_tokens: int
    omitted_paths: Tuple[str, ...]


@dataclass(frozen=True)
class EditDecision:
    allowed: bool
    path: str
    reason: str
    expected_hash: str = ""
    observed_hash: str = ""


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_JS_FUNCTION_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
)
_JS_CLASS_RE = re.compile(r"(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")
_JS_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
)
_IMPORT_RE = re.compile(
    r"(?:from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\)|"
    r"import\s+[^;\n]*?\s+from\s+['\"]([^'\"]+)['\"]|^\s*import\s+([A-Za-z0-9_./-]+))",
    re.MULTILINE,
)
_HTML_ID_RE = re.compile(r"\bid\s*=\s*['\"]([A-Za-z_][\w:-]*)['\"]", re.I)
_HTML_SCRIPT_RE = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.I | re.S)


def content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8", "replace")).hexdigest()


def detect_language(path: str, declared: str = "") -> str:
    if declared:
        return declared.lower()
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".sql": "sql",
    }.get(suffix, "text")


def _source_segment(lines: Sequence[str], start: int, end: int, limit: int = 12) -> str:
    lo = max(start - 1, 0)
    hi = min(max(end, start), lo + limit, len(lines))
    return "\n".join(lines[lo:hi])


def _python_signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args: List[str] = []
        positional = list(node.args.posonlyargs) + list(node.args.args)
        defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
        for arg, default in zip(positional, defaults):
            value = arg.arg
            if arg.annotation is not None:
                value += f": {ast.unparse(arg.annotation)}"
            if default is not None:
                value += f" = {ast.unparse(default)}"
            args.append(value)
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        elif node.args.kwonlyargs:
            args.append("*")
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            value = arg.arg
            if arg.annotation is not None:
                value += f": {ast.unparse(arg.annotation)}"
            if default is not None:
                value += f" = {ast.unparse(default)}"
            args.append(value)
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        result = f"{prefix} {node.name}({', '.join(args)})"
        if node.returns is not None:
            result += f" -> {ast.unparse(node.returns)}"
        return result
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(base) for base in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    return ""


def _python_symbols(path: str, content: str) -> Tuple[List[SymbolRecord], Set[str], Set[str]]:
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError:
        return [], set(), set()
    symbols: List[SymbolRecord] = []
    imports: Set[str] = set()
    references: Set[str] = set()
    parent_stack: List[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            imports.update(alias.name for alias in node.names)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                imports.add(node.module)
            references.update(alias.name for alias in node.names)

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Load):
                references.add(node.id)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            references.add(node.attr)
            self.generic_visit(node)

        def _record(self, node: ast.AST, kind: str) -> None:
            name = getattr(node, "name", "")
            full_name = ".".join(parent_stack + [name]) if parent_stack else name
            body_refs: Set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    body_refs.add(child.id)
                elif isinstance(child, ast.Attribute):
                    body_refs.add(child.attr)
            symbols.append(SymbolRecord(
                path=path,
                name=full_name,
                kind=kind,
                signature=_python_signature(node),
                line_start=getattr(node, "lineno", 1),
                line_end=getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                references=tuple(sorted(body_refs - {name})),
                exported=not name.startswith("_"),
            ))

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._record(node, "class")
            parent_stack.append(node.name)
            self.generic_visit(node)
            parent_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._record(node, "function" if not parent_stack else "method")
            parent_stack.append(node.name)
            self.generic_visit(node)
            parent_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._record(node, "async_function" if not parent_stack else "async_method")
            parent_stack.append(node.name)
            self.generic_visit(node)
            parent_stack.pop()

    Visitor().visit(tree)
    return symbols, imports, references


def _line_number(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _js_symbols(path: str, content: str) -> Tuple[List[SymbolRecord], Set[str], Set[str]]:
    symbols: List[SymbolRecord] = []
    for pattern, kind in (
        (_JS_FUNCTION_RE, "function"),
        (_JS_CLASS_RE, "class"),
        (_JS_ARROW_RE, "arrow_function"),
    ):
        for match in pattern.finditer(content):
            name = match.group(1)
            args = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
            signature = f"{kind} {name}({args})" if kind != "class" else f"class {name}"
            line = _line_number(content, match.start())
            symbols.append(SymbolRecord(
                path=path,
                name=name,
                kind=kind,
                signature=signature,
                line_start=line,
                line_end=line,
                exported=bool(re.search(r"\bexport\b", match.group(0))),
            ))
    imports: Set[str] = set()
    for match in _IMPORT_RE.finditer(content):
        imports.update(value for value in match.groups() if value)
    definitions = {symbol.name for symbol in symbols}
    references = set(_WORD_RE.findall(content)) - definitions
    return symbols, imports, references


def _html_symbols(path: str, content: str) -> Tuple[List[SymbolRecord], Set[str], Set[str]]:
    symbols: List[SymbolRecord] = []
    for match in _HTML_ID_RE.finditer(content):
        name = match.group(1)
        line = _line_number(content, match.start())
        symbols.append(SymbolRecord(
            path=path,
            name=name,
            kind="dom_id",
            signature=f"#{name}",
            line_start=line,
            line_end=line,
            exported=True,
        ))
    imports: Set[str] = set()
    references: Set[str] = set(_WORD_RE.findall(content))
    for script in _HTML_SCRIPT_RE.finditer(content):
        js_symbols, js_imports, js_references = _js_symbols(path, script.group(1))
        offset = _line_number(content, script.start(1)) - 1
        for symbol in js_symbols:
            symbols.append(SymbolRecord(
                path=symbol.path,
                name=symbol.name,
                kind=symbol.kind,
                signature=symbol.signature,
                line_start=symbol.line_start + offset,
                line_end=symbol.line_end + offset,
                references=symbol.references,
                exported=symbol.exported,
            ))
        imports.update(js_imports)
        references.update(js_references)
    return symbols, imports, references


def extract_symbols(document: SourceDocument) -> FileRecord:
    language = detect_language(document.path, document.language)
    if language == "python":
        symbols, imports, references = _python_symbols(document.path, document.content)
    elif language in {"javascript", "typescript"}:
        symbols, imports, references = _js_symbols(document.path, document.content)
    elif language == "html":
        symbols, imports, references = _html_symbols(document.path, document.content)
    else:
        symbols, imports, references = [], set(), set(_WORD_RE.findall(document.content))
    return FileRecord(
        path=document.path,
        language=language,
        symbols=tuple(symbols),
        imports=tuple(sorted(imports)),
        references=tuple(sorted(references)),
        content_hash=content_hash(document.content),
        line_count=max(document.content.count("\n") + 1, 1),
    )


def build_repository_map(documents: Sequence[SourceDocument]) -> RepositoryMap:
    files = tuple(extract_symbols(document) for document in documents)
    symbol_index_lists: Dict[str, List[SymbolRecord]] = defaultdict(list)
    incoming: Counter[str] = Counter()
    for file in files:
        for symbol in file.symbols:
            leaf = symbol.name.split(".")[-1]
            symbol_index_lists[leaf].append(symbol)
            symbol_index_lists[symbol.name].append(symbol)
    for file in files:
        for reference in file.references:
            if reference in symbol_index_lists:
                incoming[reference] += 1
    return RepositoryMap(
        files=files,
        symbol_index={key: tuple(value) for key, value in symbol_index_lists.items()},
        incoming_references=dict(incoming),
    )


def _query_terms(query: str) -> Set[str]:
    return {term.lower() for term in _WORD_RE.findall(query or "") if len(term) > 1}


def rank_repository_context(
    query: str,
    documents: Sequence[SourceDocument],
    repository_map: Optional[RepositoryMap] = None,
    *,
    changed_paths: Optional[Iterable[str]] = None,
    failing_paths: Optional[Iterable[str]] = None,
    token_budget: int = 4000,
    max_files: int = 12,
) -> ContextSelection:
    """Select relevant repository excerpts under a token budget."""
    repo = repository_map or build_repository_map(documents)
    by_path = {document.path: document for document in documents}
    changed = set(changed_paths or [])
    failing = set(failing_paths or [])
    terms = _query_terms(query)
    scored: List[Tuple[float, FileRecord, List[str], List[SymbolRecord]]] = []

    for file in repo.files:
        document = by_path.get(file.path)
        if document is None:
            continue
        reasons: List[str] = []
        score = 0.0
        path_terms = _query_terms(file.path)
        path_overlap = len(terms & path_terms)
        if path_overlap:
            score += 3.0 * path_overlap
            reasons.append(f"path_match={path_overlap}")
        matching_symbols = [
            symbol for symbol in file.symbols
            if terms & _query_terms(f"{symbol.name} {symbol.signature}")
        ]
        if matching_symbols:
            score += 4.0 * len(matching_symbols)
            reasons.append(f"symbol_match={len(matching_symbols)}")
        content_overlap = len(terms & {token.lower() for token in file.references})
        if content_overlap:
            score += min(content_overlap, 8) * 0.8
            reasons.append(f"reference_match={content_overlap}")
        centrality = sum(
            math.log1p(repo.incoming_references.get(symbol.name.split(".")[-1], 0))
            for symbol in file.symbols
        )
        if centrality:
            score += min(centrality, 5.0) * 0.5
            reasons.append(f"centrality={centrality:.2f}")
        if file.path in changed:
            score += 6.0
            reasons.append("changed_path")
        if file.path in failing:
            score += 10.0
            reasons.append("failing_path")
        if score > 0:
            scored.append((score, file, reasons, matching_symbols))

    scored.sort(key=lambda row: (row[0], row[1].path), reverse=True)
    items: List[ContextItem] = []
    used = 0
    selected_paths: Set[str] = set()
    for score, file, reasons, matching_symbols in scored[: max(max_files * 3, max_files)]:
        document = by_path[file.path]
        lines = document.content.splitlines()
        excerpt_parts: List[str] = [f"{file.path} [{file.language}]"]
        symbols_for_excerpt = matching_symbols or list(file.symbols[:4])
        for symbol in symbols_for_excerpt[:6]:
            excerpt_parts.append(symbol.signature or f"{symbol.kind} {symbol.name}")
            snippet = _source_segment(lines, symbol.line_start, symbol.line_end, limit=8)
            if snippet:
                excerpt_parts.append(snippet)
        if not symbols_for_excerpt:
            excerpt_parts.append("\n".join(lines[:20]))
        excerpt = "\n".join(part for part in excerpt_parts if part).strip()
        estimated = max(1, math.ceil(len(excerpt) / 4))
        if used + estimated > token_budget:
            remaining = token_budget - used
            if remaining < 64:
                continue
            excerpt = excerpt[: remaining * 4]
            estimated = max(1, math.ceil(len(excerpt) / 4))
        items.append(ContextItem(
            path=file.path,
            score=score,
            reason=tuple(reasons),
            excerpt=excerpt,
            estimated_tokens=estimated,
            symbols=tuple(symbol.name for symbol in symbols_for_excerpt[:6]),
        ))
        selected_paths.add(file.path)
        used += estimated
        if used >= token_budget or len(items) >= max_files:
            break

    omitted = tuple(file.path for file in repo.files if file.path not in selected_paths)
    return ContextSelection(tuple(items), used, token_budget, omitted)


class ReadBeforeEditGuard:
    """Require an agent to edit the exact revision it last read."""

    def __init__(self) -> None:
        self._read_hashes: Dict[str, str] = {}

    def record_read(self, path: str, content: str) -> str:
        digest = content_hash(content)
        self._read_hashes[path] = digest
        return digest

    def invalidate(self, path: str) -> None:
        self._read_hashes.pop(path, None)

    def decide(self, path: str, current_content: str, *, creating: bool = False) -> EditDecision:
        observed = content_hash(current_content)
        if creating and not current_content:
            return EditDecision(True, path, "new_file", observed_hash=observed)
        expected = self._read_hashes.get(path, "")
        if not expected:
            return EditDecision(
                False,
                path,
                "read_required_before_edit",
                observed_hash=observed,
            )
        if expected != observed:
            return EditDecision(
                False,
                path,
                "file_changed_since_read",
                expected_hash=expected,
                observed_hash=observed,
            )
        return EditDecision(
            True,
            path,
            "read_revision_matches",
            expected_hash=expected,
            observed_hash=observed,
        )
