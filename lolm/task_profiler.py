# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Ambiguity-aware task profiling for the capability core.

The original fallback classifier is intentionally retained for compatibility.
This v2 layer corrects high-impact ambiguities before model/tool routing:

* repository action verbs such as fix, repair, edit, patch, and refactor imply
  code execution even when the prompt also says research;
* mentioning a programming language does not imply code generation when the
  user is asking a factual question about that language;
* the noun ``version`` is not inherently time-sensitive. Freshness is required
  only when paired with explicit temporal language such as latest or current.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import List

from lolm.capability_router import TaskKind, TaskProfile, profile_task as profile_task_v1


_CODE_ACTION_RE = re.compile(
    r"\b(fix|repair|edit|change|modify|patch|refactor|implement|add|remove|"
    r"replace|upgrade|migrate|debug|build|create|write|generate|compile|run|"
    r"execute|test|deploy|develop|code)\b",
    re.IGNORECASE,
)
_EXPLICIT_FRESHNESS_RE = re.compile(
    r"\b(today|currently?|latest|newest|now|recent(?:ly)?|up[- ]to[- ]date|"
    r"as\s+of|this\s+(?:week|month|year)|released?\s+(?:today|this\s+week)|"
    r"current\s+version|latest\s+version|newest\s+version|version\s+released)\b",
    re.IGNORECASE,
)
_BARE_VERSION_RE = re.compile(r"\bversion\b", re.IGNORECASE)
_QUESTION_RE = re.compile(
    r"\?|^\s*(?:according\s+to\s+[^,]+,\s*)?"
    r"(?:what|why|how|when|where|who|which|is|are|does|do|can|could|should|would)\b",
    re.IGNORECASE,
)


def profile_task(
    text: str,
    *,
    has_repository: bool = False,
    supplied_sources: bool = False,
) -> TaskProfile:
    """Return a corrected deterministic profile for live capability routing."""
    content = (text or "").strip()
    base = profile_task_v1(
        content,
        has_repository=has_repository,
        supplied_sources=supplied_sources,
    )
    explicit_freshness = bool(_EXPLICIT_FRESHNESS_RE.search(content))
    code_action = bool(_CODE_ACTION_RE.search(content))
    repo_action = base.repository_context and code_action
    question = bool(_QUESTION_RE.search(content))

    kind = base.kind
    requires_execution = base.requires_execution
    requires_tools = base.requires_tools
    requires_retrieval = base.requires_retrieval
    requires_current = base.requires_current_information
    requires_structured = base.requires_structured_output
    risk = base.risk
    tags: List[str] = list(base.tags)

    # A language name can be the subject of a question rather than an execution
    # request. "What Python version is required?" must not open a coding agent.
    if question and base.language and not code_action and not repo_action:
        kind = TaskKind.CURRENT_QA if explicit_freshness else TaskKind.FACTUAL_QA
        requires_execution = False
        requires_structured = False
        requires_current = explicit_freshness
        requires_retrieval = supplied_sources or explicit_freshness
        requires_tools = explicit_freshness
        risk = 0.40 if explicit_freshness else 0.15
        tags = [tag for tag in tags if tag not in {"shell", "freshness"}]
        if explicit_freshness:
            tags.append("freshness")

    # "Python version" and "API version" are stable/source questions unless the
    # user actually asks for the current/latest release.
    if _BARE_VERSION_RE.search(content) and not explicit_freshness:
        requires_current = False
        tags = [tag for tag in tags if tag != "freshness"]
        if kind == TaskKind.CURRENT_QA:
            kind = TaskKind.FACTUAL_QA
        requires_retrieval = supplied_sources or kind in {TaskKind.RESEARCH, TaskKind.REPO_EDIT}
        if kind == TaskKind.FACTUAL_QA:
            requires_tools = False

    if explicit_freshness:
        requires_current = True
        requires_retrieval = True
        requires_tools = True
        if "freshness" not in tags:
            tags.append("freshness")
        if question and not repo_action:
            kind = TaskKind.CURRENT_QA

    # Action on an existing repository dominates research wording. Research is
    # a supporting operation, not the terminal task type.
    if repo_action:
        kind = TaskKind.REPO_EDIT
        requires_execution = True
        requires_tools = True
        requires_retrieval = True
        requires_structured = True
        risk = max(risk, 0.55)
        if "repository" not in tags:
            tags.append("repository")

    return replace(
        base,
        kind=kind,
        requires_execution=requires_execution,
        requires_tools=requires_tools,
        requires_retrieval=requires_retrieval,
        requires_current_information=requires_current,
        requires_structured_output=requires_structured,
        risk=risk,
        tags=tuple(tags),
    )
