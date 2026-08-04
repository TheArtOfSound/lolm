# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Coding technique library — durable learning for future scenarios.

LOLM does not "remember" only chat facts. This module stores reusable coding
techniques extracted from:
  1. A seeded curriculum of battle-tested patterns (canvas games, parsers, …)
  2. Sealed successful code/visual runs (when the oracle said ok / verified)

On every coding or visual task we RETRIEVE the most relevant techniques and
inject them into the agent prompt. On every success we LEARN (upsert + boost
success_count). Failures can soft-penalize a technique that was applied.

This is the flywheel for "learn every coding technique and perfect it for any
future scenario" — inspectable JSONL, not a black-box weight claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_LOCK = threading.Lock()
_PATH: Optional[Path] = None

# ── Curriculum: techniques the product should always know ───────────────────
# Tags are free-form keywords used for retrieval (snake, canvas, wrap, csv, …).
_CURRICULUM: List[Dict[str, Any]] = [
    {
        "id": "canvas-paint-every-frame",
        "title": "Canvas: paint every frame or the browser calls it blank",
        "tags": ["canvas", "game", "animation", "snake", "pong", "visual", "draw"],
        "body": (
            "Every rAF/setInterval tick: (1) clear or fillRect full background with a "
            "visible color, (2) draw ALL entities with bright fillStyle/strokeStyle "
            "(≥4 distinct colors), (3) fillText for score/UI. Call requestAnimationFrame(loop) "
            "AND invoke loop() once on load. A near-black single-color frame is a failed build."
        ),
    },
    {
        "id": "snake-coord-collision",
        "title": "Snake: coordinate equality, never object identity",
        "tags": ["snake", "game", "canvas", "collision", "grid"],
        "body": (
            "Snake body is [{x,y},…]. Self-collision and food-on-body MUST use "
            "arr.some(p => p.x===cell.x && p.y===cell.y). Never .includes(cell) or === "
            "between objects. Start mid-grid, gameOver=false, ~110ms step, ignore 180° "
            "reversals, R resets all state. Hard-draw every segment + food every frame."
        ),
    },
    {
        "id": "word-wrap-empty",
        "title": "Word wrap: empty → [], hard-break long words, width<1 raises",
        "tags": ["wrap", "text", "string", "layout"],
        "body": (
            "wrap(text, width): if width < 1 raise ValueError; if text == '' return []. "
            "Split on whitespace; never trailing spaces; words longer than width hard-split; "
            "blank line in input → '' paragraph marker in output. Do not use textwrap."
        ),
    },
    {
        "id": "csv-rfc-quotes",
        "title": "CSV: doubled quotes, commas in quotes, no phantom rows",
        "tags": ["csv", "parse", "quotes", "fix"],
        "body": (
            "Hand-rolled CSV: state machine for in_quotes. \"\" inside quotes → one \". "
            "Commas and newlines inside quotes are data. Trailing newline must not add an "
            "extra empty row. Do not import csv module when the task forbids it."
        ),
    },
    {
        "id": "jsonpath-neg-index",
        "title": "JSON path: a.b, items[i], items[-1], missing → default",
        "tags": ["jsonpath", "get", "dict", "path", "nested"],
        "body": (
            "get(obj, path, default=None): support dotted keys and [index] including "
            "negative indices. Missing step / OOR index → default (never raise). "
            "Malformed '', 'a..b', 'a[x]' → ValueError."
        ),
    },
    {
        "id": "semver-prerelease",
        "title": "Semver: prerelease < release; numeric id < alpha; ignore +build",
        "tags": ["semver", "version", "compare"],
        "body": (
            "compare(a,b) → -1/0/1. Parse major.minor.patch; strip +build. Version with "
            "prerelease is lower than same numbers without. Dot-split prerelease: numeric "
            "identifiers compare numerically and are lower than alphanumeric. Malformed → ValueError."
        ),
    },
    {
        "id": "expr-eval-shunting",
        "title": "Expression eval: precedence, unary minus, no eval/exec",
        "tags": ["expr", "evaluate", "parser", "math", "unary"],
        "body": (
            "evaluate(s): tokenize + shunting-yard or recursive descent. + - * / and (). "
            "Unary minus. Left-assoc / and *. Division by zero → ZeroDivisionError. "
            "Malformed '1 +', '(1', '', '2 ** 3' → ValueError. Never eval/exec."
        ),
    },
    {
        "id": "iso-duration",
        "title": "ISO-8601 duration → seconds",
        "tags": ["iso", "duration", "time", "parse"],
        "body": (
            "parse_duration: P + optional date (Y=365d,M=30d,W=7d,D) + optional T time "
            "(H,M,S with fractional S). Leading - negates whole duration. '', 'P', garbage → ValueError."
        ),
    },
    {
        "id": "two-sum-hash",
        "title": "Two-sum: O(n) hash map, ascending indices",
        "tags": ["two_sum", "array", "hash", "leetcode"],
        "body": (
            "two_sum(nums, target): one pass hash value→index; when target-x seen, return "
            "sorted indices. Empty / no solution → ValueError if task requires it."
        ),
    },
    {
        "id": "valid-parens-stack",
        "title": "Valid parentheses: stack of openers",
        "tags": ["parens", "brackets", "stack", "is_valid", "string"],
        "body": (
            "is_valid(s): stack openers; on closer, top must match. Empty string is valid. "
            "Interleaved ([)] is invalid. Return bool, not string 'True'/'False'."
        ),
    },
    {
        "id": "binary-search-bounds",
        "title": "Binary search: lo <= hi, mid±1, empty → -1",
        "tags": ["binary_search", "search", "array", "logn"],
        "body": (
            "binary_search(arr, target): while lo <= hi; mid = (lo+hi)//2; move lo=mid+1 or "
            "hi=mid-1. Empty arr → -1. Last element and absent cases must work."
        ),
    },
    {
        "id": "deep-merge-copy",
        "title": "Deep merge: recurse dicts, replace lists, never mutate inputs",
        "tags": ["deep_merge", "dict", "merge", "immutable"],
        "body": (
            "deep_merge(a,b): new dict; nested dicts merge recursively; non-dict values in b "
            "overwrite; lists replace (no element-wise merge). Do not mutate a or b."
        ),
    },
    {
        "id": "fix-read-before-rewrite",
        "title": "Bugfix: READ then EDIT; honor required paths and names",
        "tags": ["fix", "debug", "edit", "refactor"],
        "body": (
            "When CURRENT WORKSPACE has files: READ first, EDIT surgically. Do not collapse "
            "a multi-file layout into main.py. Keep the function/class names the task named."
        ),
    },
    {
        "id": "contract-before-done",
        "title": "Never DONE until every TASK example and reject case runs",
        "tags": ["contract", "test", "done", "verify", "quality"],
        "body": (
            "Before DONE: exercise every arrow example and every reject/ValueError case "
            "named in the TASK (including empty string). A green hello-path is not enough. "
            "Self-check prints that say FAIL must not ship."
        ),
    },
    {
        "id": "visual-self-contained-html",
        "title": "Visual apps: one HTML file, no CDN, keys on window",
        "tags": ["visual", "html", "game", "iframe", "canvas"],
        "body": (
            "Self-contained <!DOCTYPE html> with inline CSS/JS only. No CDN, no fetch. "
            "window.addEventListener('keydown'…); window.focus() on load; preventDefault on "
            "arrows. Start already running — no start menu. Touch + keyboard when interactive."
        ),
    },
    # ── Oort/Flows-derived agent harness tactics (always-on curriculum) ──
    {
        "id": "agent-single-loop-contract",
        "title": "Single-loop agent: tool results fold back; terminate on finish/max/fail",
        "tags": ["agent", "loop", "harness", "tools", "orchestration", "oort", "flows"],
        "body": (
            "One model, one loop: model returns text OR tool calls → execute tools in order → "
            "fold real results (not optimistic summaries) into context → repeat. Terminate on "
            "explicit DONE, max turns, or K consecutive tool failures. Repeated identical "
            "tool+args (3×) is thrash — change approach."
        ),
    },
    {
        "id": "agent-adversarial-verify",
        "title": "Adversarial verify: do not trust self-claim; probe rejects and blank states",
        "tags": ["verification", "adversarial", "qa", "verify", "contract", "oort", "flows"],
        "body": (
            "Before DONE, run the real contract: every example AND reject/empty path. For "
            "visuals, browser must show multi-color paint and input response — not agent prose. "
            "If only the happy path is green, keep working."
        ),
    },
    {
        "id": "agent-plan-todo-external",
        "title": "Externalize plan/todos; advance state after every real result",
        "tags": ["plan", "todo", "memory", "project-state", "continuity", "oort", "flows"],
        "body": (
            "Keep goals, plan steps, failures, and completion criteria outside chat prose "
            "(task state z_t). After each run/edit, update what is done vs open. Context wipe "
            "must not erase the objective or open criteria."
        ),
    },
    {
        "id": "agent-error-retry-policy",
        "title": "Error recovery: structured tool errors, bounded retry, then branch",
        "tags": ["error", "retry", "recovery", "debug", "harness", "oort", "flows"],
        "body": (
            "Surface real stderr/exceptions to the model. Retry the same approach at most "
            "twice; then change approach (new algorithm, smaller surface, read-before-edit). "
            "Never spin on identical failing RUN commands."
        ),
    },
    {
        "id": "agent-dual-layer-defense",
        "title": "Dual-layer defense: prompt rules + code/sandbox backstops",
        "tags": ["security", "harness", "sandbox", "permission", "oort", "flows"],
        "body": (
            "Prompt rules are not enough. Enforce no-network jail, path sandbox, schema "
            "validation, and refuse finalize without evidence. Treat model claims of safety "
            "as untrusted until the backstop confirms."
        ),
    },
    {
        "id": "agent-observability-receipt",
        "title": "Observability: seal transcripts and receipts for every session",
        "tags": ["observability", "audit", "receipt", "trace", "oort", "flows"],
        "body": (
            "Log turns, tools, exits, and control decisions. Seal a receipt (task, verdict, "
            "files, verifies, task_state). Failure analysis uses the receipt — not memory of "
            "what the model said it did."
        ),
    },
]


def _default_path() -> Path:
    env = os.environ.get("LOLM_CODE_TECHNIQUES_PATH", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "runs" / "code_techniques.jsonl"


def init(path: Optional[Path] = None) -> Path:
    global _PATH
    _PATH = Path(path) if path else _default_path()
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    return _PATH


def library_path() -> Path:
    if _PATH is None:
        return init()
    return _PATH


def _sha_id(title: str, body: str) -> str:
    return "t-" + hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()[:12]


def _load_all() -> List[Dict[str, Any]]:
    path = library_path()
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return rows


def _write_all(rows: List[Dict[str, Any]]) -> None:
    path = library_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def ensure_curriculum_seeded() -> int:
    """Idempotently seed curriculum techniques. Returns number newly added."""
    with _LOCK:
        rows = _load_all()
        have = {r.get("id") for r in rows if r.get("id")}
        added = 0
        now = int(time.time())
        for c in _CURRICULUM:
            if c["id"] in have:
                continue
            rows.append({
                **c,
                "source": "curriculum",
                "success_count": 0,
                "fail_count": 0,
                "use_count": 0,
                "created_ts": now,
                "updated_ts": now,
            })
            added += 1
        # Oort/Flows catalog (hundreds of step tactics) — optional, large, once.
        try:
            from lolm.tactics.oort_flows import iter_tactics_for_seed
            for t in iter_tactics_for_seed():
                tid = t.get("id")
                if not tid or tid in have:
                    continue
                rows.append({
                    "id": tid,
                    "title": (t.get("title") or tid)[:140],
                    "body": (t.get("body") or "")[:1200],
                    "tags": list(t.get("tags") or [])[:16],
                    "source": "oort-flows",
                    "success_count": 0,
                    "fail_count": 0,
                    "use_count": 0,
                    "created_ts": now,
                    "updated_ts": now,
                    "category": t.get("category"),
                    "flow_slug": t.get("flow_slug"),
                })
                have.add(tid)
                added += 1
        except Exception:
            pass
        if added:
            _write_all(rows)
        return added


def upsert_technique(
    *,
    title: str,
    body: str,
    tags: Sequence[str],
    source: str = "learned",
    technique_id: Optional[str] = None,
    success: Optional[bool] = None,
) -> Dict[str, Any]:
    """Insert or merge a technique; boost success/fail counters when provided."""
    ensure_curriculum_seeded()
    tid = technique_id or _sha_id(title, body)
    tags_l = sorted({re.sub(r"[^a-z0-9_+-]", "", t.lower())[:32]
                     for t in (tags or []) if t and str(t).strip()})
    tags_l = [t for t in tags_l if t][:16]
    title = (title or "technique")[:120]
    body = (body or "")[:1200]
    now = int(time.time())
    with _LOCK:
        rows = _load_all()
        for r in rows:
            if r.get("id") == tid:
                r["title"] = title or r.get("title")
                r["body"] = body or r.get("body")
                old_tags = set(r.get("tags") or [])
                r["tags"] = sorted(old_tags | set(tags_l))[:16]
                if success is True:
                    r["success_count"] = int(r.get("success_count") or 0) + 1
                elif success is False:
                    r["fail_count"] = int(r.get("fail_count") or 0) + 1
                r["updated_ts"] = now
                _write_all(rows)
                return r
        row = {
            "id": tid,
            "title": title,
            "body": body,
            "tags": tags_l,
            "source": source,
            "success_count": 1 if success is True else 0,
            "fail_count": 1 if success is False else 0,
            "use_count": 0,
            "created_ts": now,
            "updated_ts": now,
        }
        rows.append(row)
        _write_all(rows)
        return row


def _keywords(text: str) -> set:
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", (text or "").lower()))


def retrieve_techniques(task: str, limit: int = 6,
                        extra_tags: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Score techniques for this task; return top N (boosts use_count)."""
    ensure_curriculum_seeded()
    keys = _keywords(task)
    for t in extra_tags or []:
        keys.add(str(t).lower())
    # Domain boosts
    tl = (task or "").lower()
    for word, tag in (
        ("snake", "snake"), ("canvas", "canvas"), ("game", "game"),
        ("wrap", "wrap"), ("csv", "csv"), ("semver", "semver"),
        ("duration", "duration"), ("jsonpath", "jsonpath"), ("path", "path"),
        ("paren", "parens"), ("bracket", "brackets"), ("two_sum", "two_sum"),
        ("binary", "binary_search"), ("merge", "deep_merge"), ("html", "visual"),
        ("pong", "pong"), ("fix", "fix"), ("bug", "fix"),
        ("agent", "agent"), ("harness", "harness"), ("mcp", "mcp"),
        ("memory", "memory"), ("verify", "verification"), ("orchestr", "orchestration"),
        ("plan", "plan"), ("todo", "todo"), ("security", "security"),
        ("observ", "observability"), ("retry", "retry"), ("loop", "loop"),
        ("audit", "audit"), ("session", "session"), ("context", "context"),
    ):
        if word in tl:
            keys.add(tag)

    with _LOCK:
        rows = _load_all()
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for r in rows:
            tags = set(str(t).lower() for t in (r.get("tags") or []))
            blob = " ".join([
                str(r.get("title") or ""),
                str(r.get("body") or ""),
                " ".join(tags),
            ]).lower()
            score = 0.0
            score += 3.0 * len(keys & tags)
            score += 1.0 * sum(1 for k in keys if k in blob and len(k) > 3)
            # Proven techniques rise; chronically failing ones fall.
            score += 0.15 * float(r.get("success_count") or 0)
            score -= 0.08 * float(r.get("fail_count") or 0)
            # Mild recency / use prior so unused curriculum still surfaces.
            score += 0.02 * min(float(r.get("use_count") or 0), 50)
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        top = [r for _, r in scored[: max(1, min(int(limit or 6), 12))]]
        # Bump use_count for retrieved
        ids = {r["id"] for r in top if r.get("id")}
        if ids:
            now = int(time.time())
            for r in rows:
                if r.get("id") in ids:
                    r["use_count"] = int(r.get("use_count") or 0) + 1
                    r["updated_ts"] = now
            _write_all(rows)
        return top


def format_techniques_for_prompt(techs: Sequence[Dict[str, Any]],
                                 heading: str = "LEARNED CODING TECHNIQUES") -> str:
    """Compact block for system/user injection."""
    if not techs:
        return ""
    lines = [
        f"\n── {heading} (apply these; they were proven on past sealed runs / curriculum) ──",
    ]
    for i, t in enumerate(techs, 1):
        title = (t.get("title") or t.get("id") or "technique")[:100]
        body = (t.get("body") or "")[:500]
        tags = ",".join((t.get("tags") or [])[:6])
        sc = int(t.get("success_count") or 0)
        lines.append(f"{i}. [{tags}] {title}")
        lines.append(f"   {body}")
        if sc:
            lines.append(f"   (proven ×{sc})")
    lines.append("── end techniques ──\n")
    return "\n".join(lines)


def learn_from_code_receipt(receipt: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Learn techniques from a sealed code or visual receipt.

    Success (ok/verified/shipped) → upsert a task-specific technique and boost
    matching curriculum tags. Failure → soft-penalize overlapping techniques.
    """
    if not receipt:
        return []
    ensure_curriculum_seeded()
    task = (receipt.get("task") or "")[:400]
    ok = bool(receipt.get("ok") or receipt.get("verified")
              or receipt.get("verdict") in ("shipped", "verified", "ok"))
    kind = str(receipt.get("kind") or receipt.get("source") or "code")
    files = receipt.get("files") or []
    summary = (receipt.get("summary") or "")[:200]
    tags = list(_keywords(task))[:12]
    if "visual" in kind or any(str(f).endswith(".html") for f in files):
        tags += ["visual", "html", "canvas"]
    if any(k in task.lower() for k in ("snake", "game", "pong")):
        tags += ["game", "canvas"]

    learned: List[Dict[str, Any]] = []
    if ok and task:
        # Distill a short technique from this success.
        title = f"Worked: {task[:80]}"
        body_parts = [
            f"Task: {task[:240]}",
        ]
        if files:
            body_parts.append("Files: " + ", ".join(str(f) for f in files[:8]))
        if summary:
            body_parts.append(f"Summary: {summary}")
        if receipt.get("verdict"):
            body_parts.append(f"Verdict: {receipt.get('verdict')}")
        body = " | ".join(body_parts)
        row = upsert_technique(
            title=title,
            body=body,
            tags=tags,
            source="receipt:" + str(receipt.get("receipt_sha")
                                    or receipt.get("ledger_sha") or "ok")[:24],
            success=True,
        )
        learned.append(row)
        # Boost curriculum techniques that share tags
        with _LOCK:
            rows = _load_all()
            tagset = set(tags)
            changed = False
            for r in rows:
                if r.get("source") != "curriculum":
                    continue
                if tagset & set(str(t).lower() for t in (r.get("tags") or [])):
                    r["success_count"] = int(r.get("success_count") or 0) + 1
                    r["updated_ts"] = int(time.time())
                    changed = True
            if changed:
                _write_all(rows)
    elif not ok and task:
        # Soft-penalize overlapping techniques (do not delete).
        with _LOCK:
            rows = _load_all()
            keys = _keywords(task)
            for r in rows:
                tags_r = set(str(t).lower() for t in (r.get("tags") or []))
                if keys & tags_r:
                    r["fail_count"] = int(r.get("fail_count") or 0) + 1
                    r["updated_ts"] = int(time.time())
            _write_all(rows)
    return learned


def stats() -> Dict[str, Any]:
    ensure_curriculum_seeded()
    rows = _load_all()
    oort_n = sum(1 for r in rows if r.get("source") == "oort-flows")
    return {
        "path": str(library_path()),
        "n": len(rows),
        "curriculum": sum(1 for r in rows if r.get("source") == "curriculum"),
        "oort_flows": oort_n,
        "learned": sum(1 for r in rows if str(r.get("source") or "").startswith("receipt")
                       or r.get("source") == "learned"),
        "top_success": sorted(
            [{"id": r.get("id"), "title": r.get("title"),
              "success": r.get("success_count"), "use": r.get("use_count")}
             for r in rows],
            key=lambda x: -int(x.get("success") or 0),
        )[:8],
    }


def techniques_prompt_block(task: str, limit: int = 5) -> str:
    """One-call helper for agents: retrieve techniques + Oort/Flows tactics."""
    techs: List[Dict[str, Any]] = []
    try:
        techs = retrieve_techniques(task, limit=limit)
        block = format_techniques_for_prompt(techs)
    except Exception:
        block = ""
    # Layer live Oort/Flows catalog (playbook + tactics) when seed hits are thin.
    try:
        from lolm.tactics.oort_flows import tactics_prompt_block as oort_block
        already_oort = sum(
            1 for t in techs if str(t.get("source") or "") == "oort-flows"
        )
        if already_oort < 2:
            extra = oort_block(task, limit=max(2, min(4, int(limit or 5))))
            if extra:
                block = (block or "") + extra
    except Exception:
        pass
    return block or ""
