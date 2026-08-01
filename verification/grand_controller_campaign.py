# Copyright (c) 2026 Qira LLC. Verification-only campaign.
"""Run 2,048 adversarial CodeAgent simulations against the real local controller.

These are not model-quality benchmarks: the model outputs are scripted so the test can
isolate how the controller, sandbox, verifier, workspace, and receipt logic react to
known-good, malformed, repetitive, contradictory, and regressive proposals.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from local_ui.code_agent import CodeAgent
from local_ui.sandbox import Sandbox

OUT = Path(os.environ.get("GRAND_CONTROLLER_OUT", "grand-controller-results"))
OUT.mkdir(parents=True, exist_ok=True)


class ScriptedChat:
    def __init__(self, responses: Iterable[str]):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, _messages):
        if self.calls < len(self.responses):
            value = self.responses[self.calls]
        else:
            value = "DONE: no further scripted action"
        self.calls += 1
        return value


def receipt_from(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    for event in events:
        if event.get("event") == "code_receipt":
            return event.get("data") or {}
    return {}


def done_from(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    for event in events:
        if event.get("event") == "code_done":
            return event.get("data") or {}
    return {}


def notes_from(events: List[Dict[str, Any]]) -> List[str]:
    return [str((e.get("data") or {}).get("text") or "") for e in events if e.get("event") == "agent_note"]


def run_scenario(family: str, variant: int) -> Dict[str, Any]:
    token = f"v{variant:04d}"
    filename = f"solution_{token}.py"
    exact_name = f"answer_{token}.txt"
    task = ""
    responses: List[str] = []
    max_steps = 8
    expected: Dict[str, Any] = {}

    if family == "success_python":
        task = f"Create {filename} that prints exactly OK-{token}."
        responses = [
            f"FILE: {filename}\n```python\nprint('OK-{token}')\n```\nRUN: python3 {filename}",
            "DONE: verified",
        ]
        expected = {"ship": True, "required": filename}

    elif family == "success_html":
        task = f"Create exactly one index_{token}.html browser page containing READY-{token}."
        responses = [
            f"FILE: index_{token}.html\n```html\n<!doctype html><title>{token}</title><p>READY-{token}</p><script>document.body.dataset.ready='1'</script>\n```\n"
            f"RUN: python3 -c \"from pathlib import Path; s=Path('index_{token}.html').read_text(); assert 'READY-{token}' in s and '<script>' in s; print('ok')\"",
            "DONE: verified HTML",
        ]
        expected = {"ship": True, "required": f"index_{token}.html", "max_files": 1}

    elif family == "wrong_path_then_fix":
        task = f"Create {filename} defining value() and printing {variant}."
        responses = [
            f"FILE: wrong_{token}.py\n```python\ndef value(): return {variant}\nprint(value())\n```\nRUN: python3 wrong_{token}.py",
            "DONE: wrong path",
            f"FILE: {filename}\n```python\ndef value(): return {variant}\nprint(value())\n```\nRUN: python3 {filename}",
            "DONE: corrected path",
        ]
        expected = {"ship": True, "required": filename, "must_block_early_done": True}

    elif family == "required_symbol_then_fix":
        task = f"Create {filename} defining required_{token}() -> int."
        responses = [
            f"FILE: {filename}\n```python\ndef wrong_name(): return {variant}\nprint(wrong_name())\n```\nRUN: python3 {filename}",
            "DONE: wrong symbol",
            f"FILE: {filename}\n```python\ndef required_{token}(): return {variant}\nprint(required_{token}())\n```\nRUN: python3 {filename}",
            "DONE: corrected symbol",
        ]
        expected = {"ship": True, "required": filename, "must_block_early_done": True}

    elif family == "final_broken":
        task = f"Create {filename}."
        responses = [
            f"FILE: {filename}\n```python\nprint('green')\n```\nRUN: python3 {filename}",
            f"FILE: {filename}\n```python\ndef broken_(:\n```\nRUN: python3 {filename}",
            "DONE: claim success",
        ]
        expected = {"ship": False, "broken": True, "required": filename}

    elif family == "last_green_regression":
        task = f"Create {filename} printing stable-{token}."
        responses = [
            f"FILE: {filename}\n```python\nprint('stable-{token}')\n```\nRUN: python3 {filename}",
            f"FILE: {filename}\n```python\nprint('stable-{token}'\n```\nRUN: python3 {filename}",
            "DONE: use newest tree",
        ]
        expected = {"ship": False, "broken": True, "required": filename, "green_checkpoint_should_exist": True}

    elif family == "repeated_unavailable_tool":
        task = f"Create index_{token}.html and browser-verify it."
        responses = [
            f"FILE: index_{token}.html\n```html\n<!doctype html><p>{token}</p>\n```\nRUN: xdg-open index_{token}.html",
            f"RUN: xdg-open index_{token}.html",
            f"RUN: xdg-open index_{token}.html",
            f"RUN: xdg-open index_{token}.html",
            "DONE: browser verified",
        ]
        expected = {"ship": False, "repeated_command_limit": 1, "required": f"index_{token}.html"}
        max_steps = 6

    elif family == "extra_file_pollution":
        task = f"Create exactly one file named {exact_name} containing {token}."
        responses = [
            f"FILE: {exact_name}\n```\n{token}\n```\nFILE: helper_{token}.py\n```python\nprint('helper')\n```\nRUN: cat {exact_name}",
            "DONE: delivered exactly one file",
        ]
        expected = {"ship": False, "required": exact_name, "max_files": 1, "exact_contract": True}

    elif family == "exact_one_file":
        task = f"Create exactly one file named {exact_name} containing {token}."
        responses = [
            f"FILE: {exact_name}\n```\n{token}\n```\nRUN: cat {exact_name}",
            "DONE: exact delivery",
        ]
        expected = {"ship": True, "required": exact_name, "max_files": 1}

    elif family == "edit_miss_recovery":
        task = f"Create {filename} with number() returning {variant + 1}."
        responses = [
            f"FILE: {filename}\n```python\ndef number():\n    return {variant}\nprint(number())\n```\nRUN: python3 {filename}",
            f"EDIT: {filename}\n<<<\nreturn 999999\n===\nreturn {variant + 1}\n>>>",
            f"EDIT: {filename}\n<<<\n    return {variant}\n===\n    return {variant + 1}\n>>>",
            f"RUN: python3 {filename}",
            "DONE: recovered",
        ]
        expected = {"ship": True, "required": filename, "edit_miss_not_write": True}

    elif family == "no_tests_ran":
        testfile = f"test_{token}.py"
        task = f"Create {testfile} with runnable tests and prove at least one test ran."
        responses = [
            f"FILE: {testfile}\n```python\nprint('not a unittest suite')\n```\nRUN: python3 -m unittest -q {testfile[:-3]}",
            "DONE: tests passed",
        ]
        expected = {"ship": False, "no_tests_must_not_ship": True, "required": testfile}

    elif family == "missing_dependency_repair":
        task = f"Create {filename} that parses a built-in URL without third-party packages."
        responses = [
            f"FILE: {filename}\n```python\nimport requests\nprint(requests.get('https://example.com').status_code)\n```\nRUN: python3 {filename}",
            f"FILE: {filename}\n```python\nfrom urllib.parse import urlparse\nprint(urlparse('https://example.com/a').hostname)\n```\nRUN: python3 {filename}",
            "DONE: stdlib repair",
        ]
        expected = {"ship": True, "required": filename, "repair_after_dependency": True}

    elif family == "path_traversal":
        task = f"Create ../../escape_{token}.txt containing {token}."
        responses = [
            f"FILE: ../../escape_{token}.txt\n```\n{token}\n```\nRUN: cat ../../escape_{token}.txt",
            "DONE: escaped",
        ]
        expected = {"ship": False, "escape_must_not_exist": f"escape_{token}.txt"}

    elif family == "artifact_complete_overwork":
        task = f"Create exactly one {exact_name} containing {token}; stop once verified."
        block = f"FILE: {exact_name}\n```\n{token}\n```\nRUN: cat {exact_name}"
        responses = [block, block, block, block, "DONE: finally stop"]
        expected = {"ship": True, "required": exact_name, "max_productive_writes": 1, "max_files": 1}
        max_steps = 7

    elif family == "green_test_empty_stdout":
        testfile = f"test_ok_{token}.py"
        task = f"Create {testfile} with one unittest test and run it."
        responses = [
            f"FILE: {testfile}\n```python\nimport unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertEqual({variant}, {variant})\n```\nRUN: python3 -m unittest -q {testfile[:-3]}",
            "DONE: test passes",
        ]
        expected = {"ship": True, "required": testfile, "test_output_stderr_counts": True}

    elif family == "budget_after_good_artifact":
        task = f"Create {filename} printing final-{token}."
        responses = [
            f"FILE: {filename}\n```python\nprint('final-{token}')\n```\nRUN: python3 {filename}",
            f"READ: {filename}",
            f"READ: {filename}",
        ]
        expected = {"ship": True, "required": filename, "green_before_budget": True}
        max_steps = 2

    else:
        raise ValueError(f"unknown family {family}")

    started = time.time()
    with tempfile.TemporaryDirectory(prefix=f"lolm-{family}-{token}-") as td:
        root = Path(td)
        chat = ScriptedChat(responses)
        agent = CodeAgent(Sandbox(root), chat, max_steps=max_steps, run_timeout=8, isolated=None)
        fatal = None
        try:
            events = list(agent.run(task))
        except Exception as exc:  # campaign records crashes instead of hiding them
            events = []
            fatal = f"{type(exc).__name__}: {exc}"
        receipt = receipt_from(events)
        done = done_from(events)
        notes = notes_from(events)
        files = sorted(agent.sb.list_files()) if hasattr(agent, "sb") else []
        actions = list(getattr(agent, "actions", []))
        commands = [str(a.get("command") or "") for a in actions if a.get("kind") == "run"]
        writes = [str(a.get("path") or "") for a in actions if a.get("kind") == "write_file"]
        shipped = receipt.get("verdict") == "shipped" and receipt.get("ok") is True
        syntax_ok = receipt.get("syntax_ok") is True

        checks: List[Dict[str, Any]] = []
        def check(name: str, passed: bool, detail: Any = None):
            checks.append({"name": name, "pass": bool(passed), "detail": detail})

        check("no_controller_crash", fatal is None, fatal)
        check("receipt_present", bool(receipt), receipt.get("verdict"))
        check("no_false_ship", not shipped or (syntax_ok and receipt.get("verification", {}).get("execution_ok") is True), {
            "verdict": receipt.get("verdict"), "syntax_ok": receipt.get("syntax_ok"), "verification": receipt.get("verification")
        })
        if expected.get("ship") is True:
            check("expected_ship", shipped, receipt.get("summary"))
        if expected.get("ship") is False:
            check("expected_not_ship", not shipped, receipt.get("summary"))
        if expected.get("broken"):
            check("broken_receipt", receipt.get("verdict") == "broken" and receipt.get("syntax_ok") is False, receipt)
        if expected.get("required"):
            check("required_file_exists", expected["required"] in files, files)
        if expected.get("max_files") is not None:
            visible = [f for f in files if not f.startswith("__pycache__/")]
            check("exact_file_count", len(visible) <= expected["max_files"], visible)
        if expected.get("must_block_early_done"):
            check("early_done_blocked", any("required file missing" in n or "required name missing" in n for n in notes), notes)
        if expected.get("repeated_command_limit") is not None:
            counts = Counter(commands)
            max_repeat = max(counts.values(), default=0)
            check("unavailable_command_not_repeated", max_repeat <= expected["repeated_command_limit"], counts)
        if expected.get("green_checkpoint_should_exist"):
            path = root / filename
            body = path.read_text("utf8", errors="replace") if path.exists() else ""
            check("last_known_green_restored", "stable-" in body and "print('stable-" in body and body.count("(") == body.count(")"), body)
        if expected.get("exact_contract"):
            check("extra_files_block_shipping", not shipped, {"files": files, "verdict": receipt.get("verdict")})
        if expected.get("edit_miss_not_write"):
            misses = [a for a in actions if a.get("kind") == "edit_file" and not a.get("ok")]
            check("edit_miss_recorded", bool(misses), misses)
            final = (root / filename).read_text("utf8", errors="replace") if (root / filename).exists() else ""
            check("later_exact_edit_succeeds", f"return {variant + 1}" in final, final)
        if expected.get("no_tests_must_not_ship"):
            check("zero_tests_not_shipped", not shipped, {"commands": commands, "verdict": receipt.get("verdict")})
        if expected.get("repair_after_dependency"):
            check("dependency_failure_repaired", shipped and any("requests" in str(a) for a in actions), receipt.get("summary"))
        if expected.get("escape_must_not_exist"):
            outside = root.parent / expected["escape_must_not_exist"]
            check("path_escape_blocked", not outside.exists(), str(outside))
        if expected.get("max_productive_writes") is not None:
            productive = sum(1 for p in writes if p == exact_name)
            check("stops_after_verified_artifact", productive <= expected["max_productive_writes"], {"writes": writes, "calls": chat.calls})
        if expected.get("test_output_stderr_counts"):
            check("green_tests_count_as_output", done.get("produced_output") is True, done)
        if expected.get("green_before_budget"):
            check("green_artifact_survives_budget", shipped, {"done": done, "receipt": receipt})

        return {
            "schema": "lolm.grand.controller.case.v1",
            "family": family,
            "variant": variant,
            "task": task,
            "duration_ms": round((time.time() - started) * 1000, 3),
            "fatal": fatal,
            "chat_calls": chat.calls,
            "files": files,
            "commands": commands,
            "writes": writes,
            "notes": notes[-12:],
            "done": done,
            "receipt": receipt,
            "checks": checks,
            "passed": sum(1 for c in checks if c["pass"]),
            "failed": sum(1 for c in checks if not c["pass"]),
        }


FAMILIES = [
    "success_python",
    "success_html",
    "wrong_path_then_fix",
    "required_symbol_then_fix",
    "final_broken",
    "last_green_regression",
    "repeated_unavailable_tool",
    "extra_file_pollution",
    "exact_one_file",
    "edit_miss_recovery",
    "no_tests_ran",
    "missing_dependency_repair",
    "path_traversal",
    "artifact_complete_overwork",
    "green_test_empty_stdout",
    "budget_after_good_artifact",
]

records: List[Dict[str, Any]] = []
started_all = time.time()
for family in FAMILIES:
    for variant in range(128):
        record = run_scenario(family, variant)
        records.append(record)
        if record["failed"]:
            print(f"{family}/{variant}: {record['failed']} failed checks")

jsonl_path = OUT / "grand-controller-cases.jsonl"
jsonl_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", "utf8")

by_family: Dict[str, Dict[str, Any]] = {}
for family in FAMILIES:
    rows = [r for r in records if r["family"] == family]
    checks = [c for r in rows for c in r["checks"]]
    failures = Counter(c["name"] for c in checks if not c["pass"])
    by_family[family] = {
        "cases": len(rows),
        "checks": len(checks),
        "passed": sum(1 for c in checks if c["pass"]),
        "failed": sum(1 for c in checks if not c["pass"]),
        "pass_rate": (sum(1 for c in checks if c["pass"]) / len(checks)) if checks else 0,
        "median_duration_ms": sorted(r["duration_ms"] for r in rows)[len(rows) // 2],
        "failure_types": dict(failures),
    }

all_checks = [c for r in records for c in r["checks"]]
summary = {
    "schema": "lolm.grand.controller.summary.v1",
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "cases": len(records),
    "checks": len(all_checks),
    "passed": sum(1 for c in all_checks if c["pass"]),
    "failed": sum(1 for c in all_checks if not c["pass"]),
    "pass_rate": sum(1 for c in all_checks if c["pass"]) / len(all_checks),
    "duration_seconds": round(time.time() - started_all, 3),
    "families": by_family,
    "failure_types": dict(Counter(c["name"] for c in all_checks if not c["pass"])),
    "fatal_cases": sum(1 for r in records if r["fatal"]),
}
(OUT / "grand-controller-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", "utf8")
print(json.dumps(summary, indent=2, sort_keys=True))
