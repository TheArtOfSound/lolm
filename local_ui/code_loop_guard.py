# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Coding-loop guards for artifact language, capability, and recovery.

Structural controls for realistic multi-step failures (Snake forensics):
  - HTML content must never be py_compiled as Python
  - Unavailable tools are permanently blocked for the run
  - Branch must change strategy (not alias verify)
  - Repeated semantic root causes force early stop
  - Feasibility of acceptance tests is resolved at start
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HTML_MARKERS = re.compile(
    r"<!DOCTYPE\s+html|<html[\s>]|<head[\s>]|<body[\s>]|<canvas[\s>]|"
    r"<script[\s>]|requestAnimationFrame|addEventListener\s*\(\s*['\"]keydown",
    re.I,
)
_CSS_IN_PY = re.compile(
    r"^\s*(body|html|canvas|\.[\w-]+|#[\w-]+)\s*\{|@keyframes|margin\s*:|padding\s*:",
    re.I | re.M,
)
_DESKTOP_OPEN = re.compile(r"^\s*(xdg-open|open)\b", re.I)
_PY_COMPILE = re.compile(r"python3?\s+-m\s+py_compile\b", re.I)
_PY_RUN = re.compile(r"^\s*python3?\s+\S+\.py\b", re.I)


def looks_like_html(content: str) -> bool:
    c = content or ""
    if not c.strip():
        return False
    if _HTML_MARKERS.search(c[:4000]):
        return True
    # Pure CSS dumped into .py is still not Python
    if _CSS_IN_PY.search(c[:2000]) and "def " not in c[:500] and "import " not in c[:500]:
        return True
    return False


def looks_like_python(content: str) -> bool:
    c = (content or "").lstrip()
    if not c:
        return False
    if looks_like_html(c):
        return False
    return bool(re.search(
        r"^(?:#|from\s+\w|import\s+\w|def\s+\w|class\s+\w|async\s+def\s+|if\s+__name__)",
        c, re.M,
    ))


def language_for_path_and_content(path: str, content: str) -> str:
    p = (path or "").lower()
    if p.endswith((".html", ".htm")):
        return "html"
    if p.endswith(".pdf"):
        return "pdf"
    if p.endswith((".js", ".mjs")):
        return "javascript"
    if p.endswith(".css"):
        return "css"
    if p.endswith(".py"):
        if looks_like_html(content):
            return "html_misrouted"
        return "python"
    if looks_like_html(content):
        return "html"
    return "unknown"


def should_refuse_py_compile(path: str, content: Optional[str] = None) -> Tuple[bool, str]:
    """Never py_compile HTML-as-Python or non-Python paths."""
    p = (path or "").lower()
    if not p.endswith(".py"):
        return True, f"refused py_compile on non-python path {path}"
    if content is not None and looks_like_html(content):
        return True, (
            f"refused py_compile: `{path}` contains HTML/CSS/JS, not Python. "
            "Write FILE: index.html for browser tasks."
        )
    return False, ""


def redirect_html_misroute(
    path: str,
    content: str,
    *,
    primary_language: str = "",
) -> Tuple[str, str, Optional[str]]:
    """If HTML is written to main.py/solution.py for an HTML task, redirect to index.html.

    Returns (path, content, note_or_None).
    """
    lang = language_for_path_and_content(path, content)
    if lang != "html_misrouted" and not (
        looks_like_html(content) and (path or "").endswith(".py")
    ):
        return path, content, None
    if primary_language == "html" or looks_like_html(content):
        note = (
            f"language routing: `{path}` body is HTML — writing as index.html "
            "instead of compiling as Python"
        )
        return "index.html", content, note
    return path, content, None


def command_blocked_by_language(
    command: str,
    *,
    primary_language: str,
    files_written: Sequence[str],
    file_contents: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """Block py_compile / python runs that target HTML misroutes."""
    cmd = (command or "").strip()
    if not cmd:
        return False, ""
    if primary_language == "html":
        if _DESKTOP_OPEN.match(cmd):
            return True, (
                "desktop browser open is not a valid HTML verifier — use html.render"
            )
        if _PY_COMPILE.search(cmd) or _PY_RUN.match(cmd):
            # Allow only if there is a genuine .py harness separate from the app
            py_targets = re.findall(r"([A-Za-z0-9_./-]+\.py)", cmd)
            contents = file_contents or {}
            for t in py_targets:
                body = contents.get(t) or contents.get(t.rsplit("/", 1)[-1]) or ""
                if looks_like_html(body):
                    return True, (
                        f"blocked `{cmd[:60]}`: {t} is HTML content, not Python"
                    )
            # For pure HTML tasks with only index.html, block all python runs
            htmls = [p for p in files_written if (p or "").endswith((".html", ".htm"))]
            pys = [p for p in files_written if (p or "").endswith(".py")]
            if htmls and not pys:
                return True, (
                    "HTML-primary task has no Python app files — "
                    "use static lint / html.render, not python3"
                )
            # If only py files are misrouted HTML, block
            if pys and all(
                looks_like_html(contents.get(p) or "") for p in pys if p in contents
            ):
                return True, "all .py files are HTML misroutes — rewrite as index.html"
    return False, ""


def feasibility_preflight(
    primary_language: str,
    capability_facts: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve acceptance-test feasibility before mutation.

    Returns plan: verifier to use, hard_missing, waived, stop_reason.
    """
    plan: Dict[str, Any] = {
        "primary_language": primary_language,
        "verifier": "exists.path",
        "hard_missing": [],
        "substitutes": {},
        "stop_reason": "",
        "desktop_open_forbidden": True,
    }
    if primary_language == "html":
        # Never use desktop.open as acceptance
        plan["desktop_open_forbidden"] = True
        html_render = capability_facts.get("html.render")
        static = capability_facts.get("html.static_lint")
        desktop = capability_facts.get("desktop.open")
        if isinstance(html_render, dict) and html_render.get("available") is not False:
            plan["verifier"] = "html.render"
        elif isinstance(static, dict) and static.get("available") is not False:
            plan["verifier"] = "html.static_lint"
            plan["substitutes"]["html.render"] = "html.static_lint"
        else:
            plan["hard_missing"].append("html.render")
            plan["stop_reason"] = (
                "no HTML verifier available (html.render / static_lint)"
            )
        if isinstance(desktop, dict) and desktop.get("available") is False:
            plan["substitutes"]["desktop.open"] = plan["verifier"]
    elif primary_language == "python":
        plan["verifier"] = "syntax.python"
        plan["desktop_open_forbidden"] = True
    elif primary_language == "pdf":
        plan["verifier"] = "pdf.exists"
    return plan


def branch_strategy_for_html_dead_end() -> Dict[str, str]:
    """Counterfactual strategy when browser/python path failed for HTML tasks."""
    return {
        "artifact_schema": "single_html",
        "implementation_pattern": "canvas_raf_keyboard",
        "dependency_plan": "stdlib_only",
        "tool_plan": "html_static_or_chromium",
        "verifier_plan": "html.render",
        "label": "html_browser_native_no_python",
    }


def should_early_stop(
    *,
    semantic_recurrence: int,
    fail_repeats: int,
    capability_infeasible: bool,
    branch_without_change: int,
    max_semantic: int = 3,
    max_lexical: int = 4,
    max_empty_branches: int = 2,
) -> Tuple[bool, str]:
    if capability_infeasible and semantic_recurrence >= 2:
        return True, (
            "acceptance capability infeasible and root cause repeated — "
            "stop rather than burn budget"
        )
    if semantic_recurrence >= max_semantic:
        return True, f"same semantic root cause x{semantic_recurrence} without causal change"
    if fail_repeats >= max_lexical:
        return True, f"identical failure signature x{fail_repeats}"
    if branch_without_change >= max_empty_branches:
        return True, f"branch declared {branch_without_change} times without strategy change"
    return False, ""


def repair_candidate_acceptable(score_row: Dict[str, Any]) -> bool:
    """Reject repair candidates that only 'compile' but fail run as progress."""
    if score_row.get("diagnostic_only"):
        return False
    if score_row.get("run_ok") is False and score_row.get("require_run", True):
        return False
    if score_row.get("compile_ok") is False:
        return False
    if (score_row.get("score") or 0) <= 0:
        return False
    return True
