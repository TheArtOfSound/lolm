# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Guards for HTML/Python routing, capability blocks, and early stop."""

from __future__ import annotations

from local_ui.code_loop_guard import (
    branch_strategy_for_html_dead_end,
    command_blocked_by_language,
    feasibility_preflight,
    looks_like_html,
    redirect_html_misroute,
    repair_candidate_acceptable,
    should_early_stop,
    should_refuse_py_compile,
)


def test_looks_like_html_detects_canvas_game():
    html = """<!DOCTYPE html><html><body><canvas id=c></canvas>
    <script>requestAnimationFrame(loop)</script></body></html>"""
    assert looks_like_html(html) is True


def test_refuse_py_compile_on_html_in_py():
    body = "<!DOCTYPE html><html><style>body{margin:0}</style></html>"
    refuse, why = should_refuse_py_compile("main.py", body)
    assert refuse is True
    assert "HTML" in why


def test_redirect_html_misroute_to_index():
    body = "<!DOCTYPE html><html><canvas></canvas></html>"
    path, content, note = redirect_html_misroute(
        "main.py", body, primary_language="html",
    )
    assert path == "index.html"
    assert note is not None
    assert content == body


def test_command_blocks_py_compile_for_html_primary():
    blocked, why = command_blocked_by_language(
        "python3 -m py_compile main.py",
        primary_language="html",
        files_written=["index.html"],
        file_contents={"index.html": "<html></html>"},
    )
    assert blocked is True


def test_command_blocks_xdg_open_for_html():
    blocked, why = command_blocked_by_language(
        "xdg-open index.html",
        primary_language="html",
        files_written=["index.html"],
    )
    assert blocked is True
    assert "html.render" in why


def test_feasibility_forbids_desktop_open():
    plan = feasibility_preflight("html", {
        "html.render": {"available": True},
        "desktop.open": {"available": False},
    })
    assert plan["desktop_open_forbidden"] is True
    assert plan["verifier"] in ("html.render", "html.static_lint")


def test_early_stop_on_capability_recurrence():
    stop, why = should_early_stop(
        semantic_recurrence=3,
        fail_repeats=2,
        capability_infeasible=True,
        branch_without_change=0,
    )
    assert stop is True


def test_repair_rejects_run_failed():
    assert repair_candidate_acceptable({
        "compile_ok": True, "run_ok": False, "require_run": True, "score": 5,
    }) is False
    assert repair_candidate_acceptable({
        "compile_ok": True, "run_ok": True, "require_run": True, "score": 5,
    }) is True


def test_branch_strategy_html_is_non_python():
    s = branch_strategy_for_html_dead_end()
    assert s["artifact_schema"] == "single_html"
    assert "python" not in s["verifier_plan"]
    assert s["tool_plan"] != "xdg-open"
