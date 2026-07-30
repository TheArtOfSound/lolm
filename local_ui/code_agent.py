# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Agentic coding loop — the agent writes code, runs it, reads the failure, fixes it.

The "Claude Code" inner loop on LOLM's isolated sandbox. Each turn the model emits a
COMPLETE file (as a fenced code block — the format LLMs are actually reliable at, unlike
escaping a whole program inside a JSON string) plus a RUN command, or DONE. The loop
writes + runs it for real in the bwrap jail, feeds the actual stdout/exit back, and
iterates until the program runs AND prints the expected output. Everything is real and
recorded — the model only proposes; the loop is the sole thing that touches the sandbox.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, Iterator, List, Optional
SYSTEM = (
    "You are LOLM Code — an agentic coding system competing with Claude Code and Codex.\n"
    "Win by: (1) correct code that RUNS, (2) fixing real failures from REAL stdout/stderr, "
    "(3) multi-file projects when needed, (4) never claiming success without a green run.\n\n"
    "Sandbox: python3 + node + coreutils. Isolated Linux jail.\n"
    "HARD LIMITS (violations always fail):\n"
    "- NO network (no requests/urllib/fetch/APIs).\n"
    "- NO pip/npm install — stdlib only.\n"
    "- NO GUI (no pygame/tkinter/matplotlib windows).\n"
    "- NO interactive input() — use fixed sample values.\n"
    "- Must RUN AND EXIT in ~20s (no servers, no infinite loops).\n"
    "If the task needs network/GUI/server, ship a self-contained simulation that PRINTS results.\n\n"
    "Prefer the FILE/RUN text format (most reliable). You may also use JSON tools.\n\n"
    "Text format (you may emit MULTIPLE FILE blocks, then one RUN):\n"
    "FILE: <path>\n"
    "```\n"
    "<complete file contents>\n"
    "```\n"
    "RUN: <command>\n"
    "READ: <path>          # re-read a file (its content also appears in CURRENT WORKSPACE)\n"
    "EDIT: <path>          # surgical fix — old text must match the file BYTE-FOR-BYTE,\n"
    "                      # including indentation. Copy it out of CURRENT WORKSPACE.\n"
    "<<<\n"
    "<exact old text>\n"
    "===\n"
    "<replacement>\n"
    ">>>\n\n"
    "JSON tool schema (single or multi-step in one turn):\n"
    '{"action":"write_file","path":"main.py","content":"..."}  or\n'
    '{"action":"run","command":"python3 main.py"}  or\n'
    '{"action":"read_file","path":"main.py"}  or\n'
    '{"action":"edit_file","path":"main.py","old":"...","new":"..."}  or\n'
    '{"action":"list_files"}  or\n'
    '{"action":"finish","summary":"..."}  or multi:\n'
    '{"actions":[{"action":"write_file",...},{"action":"run",...}]}\n'
    "Also accepted: write_and_run with path+content+command in one object.\n\n"
    "When the run fully satisfies the TASK (and any tests you added), reply ONLY:\n"
    "DONE: <one-line summary>\n\n"
    "Quality bar:\n"
    "- HONOR THE REQUESTED SHAPE. If the TASK names files, function signatures, or a "
    "module layout, produce EXACTLY those, at exactly those paths. Never collapse a "
    "requested layout into main.py. Callers import these names — a correct program at "
    "the wrong path is a FAILURE.\n"
    "- BUILD ONLY WHAT THE TASK ASKS. Do not invent extra requirements, extra cases, or "
    "extra assertions the TASK never stated, then fail your own invention. When the TASK "
    "gives examples, those are the contract.\n"
    "- When a CURRENT WORKSPACE block is present it is the real on-disk content. Prefer "
    "EDIT with old-text copied verbatim from it; full FILE rewrite only for a new file "
    "or a deliberate restructure.\n"
    "- Prefer small pure functions + a main that prints clear results.\n"
    "- For non-trivial logic, add a self-check and RUN it. If the TASK asks for tests, "
    "write test_<name>.py using unittest.TestCase subclasses with self.assertEqual / "
    "self.assertRaises — that shape runs under BOTH pytest and `python3 -m unittest`, "
    "so it works whether or not pytest is in the jail.\n"
    "- On failure: read the error, fix ROOT CAUSE, do not rewrite the same broken code.\n"
    "- Never DONE until you have SEEN exit 0 with meaningful printed output.\n"
    "- The harness may auto-finish when expected output or tests already pass."
)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.S)
_FILE = re.compile(r"FILE\s*:\s*([\w./\-]{1,80})", re.IGNORECASE)
_RUN = re.compile(r"RUN\s*:\s*(.+)", re.IGNORECASE)
_DONE = re.compile(r"DONE\s*:\s*(.+)", re.IGNORECASE)
_READ = re.compile(r"READ\s*:\s*([\w./\-]{1,80})", re.IGNORECASE)
_LIST = re.compile(r"LIST\s*:\s*(files)?\s*$", re.IGNORECASE | re.M)
_EDIT_BLOCK = re.compile(
    r"EDIT\s*:\s*([\w./\-]{1,80})\s*\n<<<\n(.*?)\n===\n(.*?)\n>>>",
    re.S | re.IGNORECASE,
)
_FILE_BLOCK = re.compile(
    r"FILE\s*:\s*([\w./\-]{1,80})\s*\n```[a-zA-Z0-9_+\-]*\n(.*?)```",
    re.S | re.IGNORECASE,
)
_LANG_EXT = {"python": "py", "py": "py", "python3": "py", "javascript": "js", "js": "js",
             "node": "js", "bash": "sh", "sh": "sh", "shell": "sh", "go": "go"}

# Third-party packages the sandbox cannot install — coach stdlib rewrites instead of
# inventing a fake sibling module (Claude Code users install; we simulate).
_THIRD_PARTY_MODS = frozenset({
    "requests", "urllib3", "httpx", "aiohttp", "numpy", "np", "pandas", "pd",
    "scipy", "sklearn", "torch", "tensorflow", "tf", "keras", "flask", "django",
    "fastapi", "bs4", "beautifulsoup4", "lxml", "PIL", "pillow", "cv2", "opencv",
    "matplotlib", "seaborn", "plotly", "openai", "anthropic", "tiktoken",
    "langchain", "transformers", "datasets", "huggingface_hub", "boto3", "botocore",
    "redis", "sqlalchemy", "psycopg2", "pymongo", "selenium", "playwright",
    "pytest", "hypothesis", "pydantic", "yaml", "toml", "dotenv", "rich", "typer",
    "click", "tqdm", "joblib", "numba", "sympy", "networkx", "scrapy",
})

# Test frameworks are absent from the jail like any other third-party package, but they
# need their OWN coach: the generic "rewrite with stdlib only" message reads as license
# to delete the tests, which is the opposite of what a test-shaped task wants.
_TEST_FRAMEWORK_MODS = frozenset({"pytest", "hypothesis", "nose", "nose2"})

# Chars of unified diff sent per file_changed event. The sandbox already retains up to
# _OUTPUT_CAP (24k) per change, so the old 2500 threw away data it had — and clients
# that rebuild files from the stream (`lolm-cli code --save`) could not reconstruct
# anything past a couple of hundred lines. Matched to the sandbox's own cap.
_DIFF_CAP = 24000

# Canonical empty turn shape
_EMPTY_TURN = {
    "files": [], "file": None, "run": None, "done": None,
    "reads": [], "edits": [], "list": False,
}


def _json_blobs(text: str) -> List[Any]:
    """Extract top-level JSON objects/arrays from model text (best-effort)."""
    if not text:
        return []
    out: List[Any] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] not in "{[":
            i += 1
            continue
        stack: List[str] = []
        in_str = False
        esc = False
        start = i
        j = i
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                j += 1
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack:
                    break
                open_ch = stack.pop()
                if (open_ch, ch) not in (("{", "}"), ("[", "]")):
                    break
                if not stack:
                    chunk = text[start:j + 1]
                    try:
                        out.append(json.loads(chunk))
                    except json.JSONDecodeError:
                        pass
                    i = j + 1
                    break
            j += 1
        else:
            break
        if j >= n and stack:
            break
        if i == start:
            i += 1
    return out


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull a JSON action object out of a reply (legacy/strict format)."""
    for obj in _json_blobs(text):
        if isinstance(obj, dict) and (obj.get("action") or obj.get("actions")):
            return obj
    return None


def _norm_action(a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one JSON tool call into internal turn fields."""
    if not isinstance(a, dict):
        return None
    act = str(a.get("action") or a.get("tool") or "").strip().lower()
    if not act and a.get("path") and ("content" in a or "old" in a):
        act = "edit_file" if a.get("old") is not None else "write_file"
    if act in ("write_file", "write", "create_file", "create"):
        pair = (a.get("path") or "main.py", a.get("content") or a.get("code") or "")
        return {"files": [pair], "run": a.get("command") or a.get("run")}
    if act in ("write_and_run", "write_run"):
        pair = (a.get("path") or "main.py", a.get("content") or a.get("code") or "")
        cmd = a.get("command") or a.get("run") or f"python3 {pair[0]}"
        return {"files": [pair], "run": cmd}
    if act in ("run", "shell", "bash", "exec"):
        return {"run": a.get("command") or a.get("cmd") or a.get("shell")}
    if act in ("finish", "done", "complete"):
        return {"done": a.get("summary") or a.get("message") or "done"}
    if act in ("read_file", "read", "cat", "open"):
        p = a.get("path") or a.get("file")
        return {"reads": [p]} if p else None
    if act in ("edit_file", "edit", "str_replace", "search_replace", "patch"):
        p = a.get("path") or a.get("file")
        old = a.get("old") if "old" in a else a.get("find") or a.get("search")
        new = a.get("new") if "new" in a else a.get("replace") or a.get("replacement")
        if p is not None and old is not None and new is not None:
            return {"edits": [(p, str(old), str(new))]}
        return None
    if act in ("list_files", "list", "ls"):
        return {"list": True}
    return None


def _merge_turn_bits(*bits: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    t = dict(_EMPTY_TURN)
    t["files"] = []
    t["reads"] = []
    t["edits"] = []
    for b in bits:
        if not b:
            continue
        for f in b.get("files") or []:
            t["files"].append(f)
        for r in b.get("reads") or []:
            if r and r not in t["reads"]:
                t["reads"].append(r)
        for e in b.get("edits") or []:
            t["edits"].append(e)
        if b.get("run"):
            t["run"] = b["run"]
        if b.get("done"):
            t["done"] = b["done"]
        if b.get("list"):
            t["list"] = True
    t["file"] = t["files"][0] if t["files"] else None
    return t


def _parse_json_tools(text: str) -> Optional[Dict[str, Any]]:
    """Parse single/multi JSON tool calls into a unified turn."""
    blobs = _json_blobs(text)
    if not blobs:
        return None
    bits: List[Dict[str, Any]] = []
    for obj in blobs:
        if isinstance(obj, list):
            for item in obj:
                n = _norm_action(item) if isinstance(item, dict) else None
                if n:
                    bits.append(n)
            continue
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("actions"), list):
            for item in obj["actions"]:
                n = _norm_action(item) if isinstance(item, dict) else None
                if n:
                    bits.append(n)
            continue
        n = _norm_action(obj)
        if n:
            bits.append(n)
    if not bits:
        return None
    t = _merge_turn_bits(*bits)
    if t["files"] or t["run"] or t["done"] or t["reads"] or t["edits"] or t["list"]:
        return t
    return None


def _parse_turn(text: str) -> Optional[Dict[str, Any]]:
    """Unified parser → files list + run + done + reads/edits.

    Returns dict with keys:
      files, file, run, done, reads, edits, list
    Multi-FILE turns and multi-action JSON are first-class (Claude/Codex parity).
    """
    if not text or not text.strip():
        return None
    # JSON tools first (single action, actions[], write_and_run, …)
    jt = _parse_json_tools(text)
    if jt and (jt.get("files") or jt.get("run") or jt.get("done")
               or jt.get("reads") or jt.get("edits") or jt.get("list")):
        # Allow hybrid: JSON write + textual RUN/DONE leftovers
        if not jt.get("run"):
            runm = _RUN.search(text)
            if runm:
                jt["run"] = runm.group(1).strip().strip("`").strip()
        if not jt.get("done"):
            dm = _DONE.search(text)
            if dm and not jt.get("files") and not jt.get("run"):
                jt["done"] = dm.group(1).strip()
        return jt

    files = [(m.group(1), m.group(2)) for m in _FILE_BLOCK.finditer(text)]
    runm = _RUN.search(text)
    cmd = runm.group(1).strip().strip("`").strip() if runm else None
    reads = [m.group(1) for m in _READ.finditer(text)]
    edits = [(m.group(1), m.group(2), m.group(3)) for m in _EDIT_BLOCK.finditer(text)]
    wants_list = bool(_LIST.search(text)) or bool(re.search(r"^\s*LIST\s*$", text, re.I | re.M))

    if not files:
        fence = _FENCE.search(text)
        content = fence.group(1) if fence else None
        if content is not None or cmd is not None:
            name = None
            fm = _FILE.search(text)
            if fm:
                name = fm.group(1)
            if not name and content is not None:
                lang = re.search(r"```([a-zA-Z0-9_+\-]+)", text)
                name = "main." + _LANG_EXT.get((lang.group(1).lower() if lang else ""), "py")
            if content is not None:
                files = [(name, content)]

    if files or cmd is not None or reads or edits or wants_list:
        first = files[0] if files else None
        return {
            "files": files, "file": first, "run": cmd, "done": None,
            "reads": reads, "edits": edits, "list": wants_list,
        }

    dm = _DONE.search(text)
    if dm:
        return {
            "files": [], "file": None, "run": None, "done": dm.group(1).strip(),
            "reads": [], "edits": [], "list": False,
        }
    return None


_FILENAME_IN_TASK = re.compile(
    r"\b([A-Za-z_][\w\-]{0,40}\.(?:py|js|mjs|ts|json|txt|md|html|css|sh))\b")


def _task_target_files(task: str) -> List[str]:
    """Paths the TASK explicitly names, in order of first mention.

    The first-turn scaffold used to hard-code ``FILE: main.py``, which out-shouted
    any path the task actually asked for — a task saying "create solution.py"
    reliably produced main.py, so anything that imported the requested module failed
    outright no matter how good the code was.
    """
    out: List[str] = []
    for m in _FILENAME_IN_TASK.finditer(task or ""):
        p = m.group(1)
        if p not in out:
            out.append(p)
    return out


# Names the task says the code must EXPOSE. Only read after a definitional cue, so
# ordinary prose like "it prints(x)" cannot manufacture a phantom requirement — a
# wrongly-required symbol would block DONE forever.
_DEFN_CUE = re.compile(
    r"\b(?:defin(?:e|es|ing)|implement(?:s|ing)?|expos(?:e|es|ing)|"
    r"provid(?:e|es|ing)|declar(?:e|es|ing))\b", re.I)
# No whitespace before the paren: a real signature is `merge(intervals)`, whereas
# prose like "[start, end] pairs (unsorted)" or "subtractive forms (IV, IX)" always
# has a space — and those produced phantom requirements that could never be satisfied.
_SIG = re.compile(r"\b([A-Za-z_]\w*)\(")
_NOT_A_SYMBOL = frozenset({
    "print", "return", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "len", "range", "open", "type", "abs", "min", "max", "sum", "sorted", "enumerate",
    "zip", "map", "filter", "round", "isinstance", "getattr", "hasattr", "repr",
    "raise", "if", "for", "while", "and", "or", "not", "in", "is", "e", "g", "eg",
    "etc", "ValueError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError",
    "class", "def", "self", "note", "eval", "exec",
})


def _task_required_symbols(task: str) -> List[str]:
    """Function/class names the TASK explicitly says to define.

    A correct implementation under a different name is as useless as one at the wrong
    path — the caller imports the name it asked for. The loop verifies this the same
    way it verifies the filename, rather than trusting the model to have complied.
    """
    t = task or ""
    out: List[str] = []
    for cue in _DEFN_CUE.finditer(t):
        # Read to the end of the sentence OR the next definitional cue, whichever comes
        # first. Stopping at the next cue keeps a class's METHODS out of the list:
        # "defining a class LRU(capacity) implementing … with get(key)" must require
        # only LRU, since get/put are attributes of the instance, not the module.
        seg = t[cue.end(): cue.end() + 240]
        seg = re.split(r"(?<=[.;])\s|\n", seg, maxsplit=1)[0]
        nxt = _DEFN_CUE.search(seg)
        if nxt:
            seg = seg[: nxt.start()]
        for m in _SIG.finditer(seg):
            name = m.group(1)
            if name in _NOT_A_SYMBOL or not name.isidentifier():
                continue
            if name not in out:
                out.append(name)
        # Only the FIRST clause that names anything sets the contract. Later clauses
        # describe behaviour — "a class LRU(capacity) implementing … with get(key)"
        # must require LRU alone, since get/put live on the instance, not the module.
        # Under-enforcing is safe (the caller's own tests still catch it); over-
        # enforcing would demand a module-level name that can never appear and would
        # deadlock the loop against a requirement the task never made.
        if out:
            break
    return out[:4]


def _wants_tests(task: str) -> bool:
    t = (task or "").lower()
    return any(k in t for k in (
        "test", "unittest", "pytest", "assert", "tdd", "spec", "verify",
    ))


def _is_test_command(cmd: str) -> bool:
    c = (cmd or "").lower()
    return "unittest" in c or "pytest" in c


def _is_test_path(path: str) -> bool:
    p = (path or "").replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in f"/{p}/"
        or p.startswith("tests/")
    )


def _pick_verify_command(files_written: List[str], task: str) -> Optional[str]:
    """Choose a post-green-run oracle. Prefer real tests over py_compile.

    Competitive bar vs Claude Code / Codex: if the agent wrote test files, run
    them (unittest discovery — always in stdlib; pytest when present). Otherwise
    for test-oriented or multi-file Python work, at least py_compile so we never
    DONE on syntax-broken trees.
    """
    py = [p for p in (files_written or []) if (p or "").endswith(".py")]
    if not py:
        return None
    tests = [p for p in py if _is_test_path(p)]
    if tests:
        # unittest is stdlib; try pytest first when it happens to be in the jail.
        # Single shell line so sandbox.run stays one command. The fallback names the
        # test MODULES explicitly rather than using `discover -p 'test*.py'`: discovery
        # silently collects nothing for an accepted layout like foo_test.py and then
        # exits 5 (NO TESTS RAN), so the verify could never go green and the loop
        # could never converge no matter how correct the code was.
        mods = [re.sub(r"\.py$", "", t).replace("/", ".") for t in tests]
        return (
            "python3 -c \"import importlib.util as u,sys; sys.exit(0 if u.find_spec('pytest') else 1)\" "
            "&& python3 -m pytest -q --tb=line "
            + " ".join(tests)
            + " || python3 -m unittest -q "
            + " ".join(mods)
        )
    if _wants_tests(task) or len(py) >= 2:
        return "python3 -m py_compile " + " ".join(py)
    return None


def _expected_outputs(task: str) -> List[str]:
    """Pull concrete expected outputs from the task text (print 42, "hello", …).

    Used to block DONE when the last green run never actually printed what the
    user asked for — a common Claude/Codex fail mode we refuse to ship.
    """
    t = task or ""
    out: List[str] = []
    for m in re.finditer(
        r"""(?:print(?:s)?|output|return|show|equals?|should\s+be|must\s+(?:print|output|return))\s+"""
        r"""(?:the\s+)?(?:number\s+|string\s+|result\s+)?["']([^"']{1,60})["']""",
        t, re.I,
    ):
        out.append(m.group(1))
    for m in re.finditer(
        r"""(?:print(?:s)?|output|return|show|equals?|should\s+be)\s+"""
        r"""(?:the\s+)?(?:number\s+)?(\d{1,12})\b""",
        t, re.I,
    ):
        out.append(m.group(1))
    # bare "print 42" / "print hello world" without quotes
    for m in re.finditer(r"\bprint\s+(\d{1,12})\b", t, re.I):
        out.append(m.group(1))
    # de-dupe preserve order
    seen = set()
    uniq: List[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq[:6]


def _last_stdout(actions: List[Dict[str, Any]]) -> str:
    for a in reversed(actions or []):
        if a.get("kind") == "run":
            r = a.get("result") or {}
            # skip verify-only commands when looking for task output
            cmd = (a.get("command") or "")
            if a.get("verify") or "py_compile" in cmd or "pytest" in cmd or "unittest" in cmd:
                continue
            if r.get("exit_code") == 0 and not r.get("blocked"):
                return (r.get("stdout") or "")
    return ""


def _task_oracle_satisfied(task: str, actions: List[Dict[str, Any]],
                           files_written: List[str]) -> Optional[str]:
    """Return a DONE summary if objective oracles say the task is complete.

    Speed + reliability: when expected stdout appears (or tests go green), finish
    without waiting for the model to say DONE — Claude/Codex users expect the
    loop to stop when the check passes.
    """
    last_out = _last_stdout(actions)
    expect = _expected_outputs(task)
    if expect:
        if last_out and all(e in last_out for e in expect):
            return f"auto-verified: printed {', '.join(expect)}"
        return None
    # Test files present → require a green verify command
    if any(_is_test_path(p) for p in (files_written or [])):
        for a in reversed(actions or []):
            if a.get("kind") != "run":
                continue
            cmd = a.get("command") or ""
            if "pytest" in cmd or "unittest" in cmd:
                r = a.get("result") or {}
                if r.get("exit_code") == 0 and not r.get("blocked"):
                    return "auto-verified: tests passed"
                return None
        return None
    # Simple print-style tasks with a clean non-empty run and no open failures
    tlow = (task or "").lower()
    if any(k in tlow for k in ("print", "hello", "fib", "prime", "factorial", "fizz")):
        if last_out and last_out.strip():
            # only auto-stop if the last non-verify run is green
            for a in reversed(actions or []):
                if a.get("kind") != "run" or a.get("verify"):
                    continue
                r = a.get("result") or {}
                if r.get("exit_code") == 0 and not r.get("blocked"):
                    return "auto-verified: clean run with output"
                break
    return None


_STDLIB_MODS = frozenset("""
abc argparse array ast asyncio base64 bisect builtins cmath collections
concurrent contextlib copy csv dataclasses datetime decimal enum functools
glob hashlib heapq hmac html http importlib io itertools json logging
math mimetypes multiprocessing numbers operator os pathlib pickle
platform pprint queue random re secrets shutil signal socket sqlite3
statistics string struct subprocess sys tempfile textwrap threading time
timeit typing unittest urllib uuid warnings weakref xml zipfile zlib
""".split())

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*))",
    re.M,
)


def _local_modules_needed(file_contents: Dict[str, str]) -> List[str]:
    """Local .py modules imported by written files (multi-file completeness)."""
    needed: set = set()
    written = {p.replace("\\", "/") for p in file_contents}
    written_mods = {p.rsplit("/", 1)[-1][:-3] for p in written if p.endswith(".py")}
    for path, content in file_contents.items():
        if not (path or "").endswith(".py"):
            continue
        for m in _IMPORT_RE.finditer(content or ""):
            raw = m.group(1) or m.group(2) or ""
            for part in raw.split(","):
                mod = part.strip().split()[0] if part.strip() else ""
                top = mod.split(".")[0]
                if not top or top in _STDLIB_MODS:
                    continue
                # only flag modules we already treat as project-local (also written)
                # OR that look like sibling modules referenced but missing
                candidate = top + ".py"
                if top in written_mods or candidate in written:
                    continue
                # if any written file shares a package style name, require the import
                # when the import matches a basename that was referenced as local
                if top[0].islower() or top[:1].isupper():
                    # skip obvious third-party (requests, numpy, …) unless also written
                    if top in ("requests", "numpy", "pandas", "flask", "django", "torch",
                               "pytest", "fastapi", "bs4", "PIL", "cv2"):
                        continue
                    needed.add(candidate)
    # Only keep missing ones
    return sorted(p for p in needed if p not in written and p.rsplit("/", 1)[-1][:-3] not in written_mods)


class CodeAgent:
    def __init__(self, sandbox: Any, chat_fn: Callable[[List[Dict[str, str]]], str],
                 max_steps: int = 18, run_timeout: int = 25,
                 isolated: Optional[bool] = True):
        self.sb = sandbox
        self.chat = chat_fn
        self.max_steps = max_steps
        self.run_timeout = run_timeout
        self.isolated = isolated
        self.actions: List[Dict[str, Any]] = []
        self._format_nudge = ""
        self._files_written: List[str] = []

    # Total chars of file content rendered per turn. The gateway caps OUTPUT tokens but
    # never the prompt, so this is the only guard against pushing SYSTEM out of the
    # context window — which would break FILE/RUN parsing and trip the 3-strike bailout.
    _WS_BUDGET = 7000
    _SKIP_EXT = (".pyc", ".pyo", ".so", ".png", ".jpg", ".jpeg", ".gif", ".zip",
                 ".pdf", ".ico", ".woff", ".woff2", ".ttf")

    def _workspace_block(self) -> str:
        """The exact on-disk content of the files in play.

        Without this the model saw only ``- wrote solution.py (2524 bytes)`` and had to
        reconstruct the file from memory every single turn, so a blind full rewrite was
        the only rational move — and each rewrite could silently clobber the parts that
        already worked. Raw bytes, deliberately NO line numbers: EDIT matches by exact
        substring, so a gutter number copied into the old text guarantees a miss.
        """
        try:
            names = [f for f in self.sb.list_files(limit=60)
                     if "__pycache__" not in f and not f.endswith(self._SKIP_EXT)]
        except Exception:
            return ""
        if not names:
            return ""
        # Most-recently-touched first — that is the file actually being iterated on.
        order = [p for p in reversed(self._files_written) if p in names]
        order += [p for p in names if p not in order]
        budget = self._WS_BUDGET
        blocks: List[str] = []
        for path in order:
            if budget <= 200:
                break
            try:
                body = self.sb.read_file(path)
            except Exception:
                continue
            if len(body) > budget:
                keep = max(budget - 120, 200)
                head, tail = body[: keep // 2], body[-(keep - keep // 2):]
                body = (head + f"\n\n... [{len(body) - keep} chars omitted — do NOT EDIT "
                        f"against this elided region; rewrite the whole FILE instead] ...\n\n"
                        + tail)
            budget -= len(body)
            blocks.append(f"--- {path} ({len(body)} bytes) ---\n{body}")
        if not blocks:
            return ""
        return ("\n\nCURRENT WORKSPACE — the real content on disk right now. Copy EDIT "
                "old-text verbatim out of this:\n" + "\n".join(blocks))

    def _missing_targets(self, task: str) -> List[str]:
        """Paths the TASK named that are not actually on disk.

        The scaffold now asks for the right filename, but a 70B model still drifts to
        a name of its own choosing. Since the caller will import exactly what the task
        specified, a missing target is a hard failure — so the loop verifies it rather
        than trusting the model to have complied.
        """
        targets = _task_target_files(task)
        if not targets:
            return []
        try:
            have = set(self.sb.list_files(limit=200))
        except Exception:
            return []
        return [t for t in targets if t not in have]

    def _missing_symbols(self, task: str) -> List[str]:
        """Required names the produced module does not actually expose.

        Imports the module inside the jail and asks it, rather than grepping the
        source — a name defined inside a conditional or a class body still counts,
        and a name that only appears in a comment does not.
        """
        want = _task_required_symbols(task)
        py = [t for t in _task_target_files(task) if t.endswith(".py")]
        if not want or not py:
            return []
        mod = re.sub(r"\.py$", "", py[0]).replace("/", ".")
        probe = (
            "python3 -c \"import importlib;"
            f"m=importlib.import_module('{mod}');"
            f"print('LOLM_MISSING:'+','.join([n for n in {want!r} if not hasattr(m,n)]))\""
        )
        try:
            r = self.sb.run(probe, timeout=min(15, max(self.run_timeout, 5)),
                            isolated=self.isolated)
        except Exception:
            return []
        if r.get("exit_code") != 0 or r.get("blocked"):
            return []      # cannot even import — the compile gate owns that failure
        for line in reversed((r.get("stdout") or "").splitlines()):
            if line.startswith("LOLM_MISSING:"):
                return [x for x in line.split(":", 1)[1].split(",") if x]
        return []

    def _recent_actions(self, keep: int = 12) -> List[Dict[str, Any]]:
        """Recent actions with GREEN verify runs collapsed out.

        One write+run step appends up to four rows (write, py_compile verify, run, test
        verify), so a flat [-8:] window held barely two turns of history. A py_compile
        that exited 0 carries no information — but a FAILING verify is the single most
        informative row there is, so only the green ones are dropped.
        """
        useful = [a for a in self.actions
                  if not (a.get("verify") and (a.get("result") or {}).get("exit_code") == 0)]
        return useful[-keep:]

    def _context(self, task: str = "") -> str:
        ws = self._workspace_block()
        if not self.actions:
            if ws:
                # Files already exist (a fix / refactor task). Telling the model
                # "nothing run yet, write the complete program" here made it clobber
                # the very code it was asked to repair.
                base = ("\n\n(These files ALREADY EXIST — the CURRENT WORKSPACE block below "
                        "is their exact content. Change only what the TASK requires, with "
                        "EDIT blocks where you can, keeping every existing module, class, "
                        "and function name. Then RUN to check your work.)")
            else:
                targets = _task_target_files(task)
                primary = targets[0] if targets else "main.py"
                extra = ""
                if len(targets) > 1:
                    extra = ("\nThe TASK names several files — create EVERY one, at exactly "
                             "these paths: " + ", ".join(targets) + ".")
                base = (f"\n\n(Nothing run yet. Write the code and run it.{extra}\n"
                        f"Reply EXACTLY:\nFILE: {primary}\n```\n<code>\n```\n"
                        f"RUN: {self._auto_run_cmd(primary)})")
            # Speed-to-value: surface concrete expected stdout on the first turn
            # so the model aims correctly without burning a mismatch cycle.
            expect = _expected_outputs(task or "")
            if expect:
                base += ("\n\nEXPECTED STDOUT (must appear after RUN):\n- "
                         + "\n- ".join(repr(e) for e in expect[:4]))
            return base + ws + (self._format_nudge or "")
        lines = ["\n\nSO FAR:"]
        for a in self._recent_actions():
            kind = a.get("kind")
            if kind == "write_file":
                lines.append(f"- wrote {a['path']} ({a.get('bytes', 0)} bytes)")
            elif kind == "read_file":
                # Content lives in CURRENT WORKSPACE (always fresh); echoing the
                # snapshot here would duplicate it and go stale after the next write.
                lines.append(f"- read {a['path']} ({a.get('bytes', 0)} bytes) — "
                             f"its current content is in CURRENT WORKSPACE below")
            elif kind == "edit_file":
                lines.append(f"- edited {a['path']} (ok={a.get('ok')}, {a.get('note', '')})")
            elif kind == "list_files":
                lines.append(f"- listed files: {', '.join(a.get('files') or []) or '(empty)'}")
            else:
                r = a.get("result") or {}
                out = ((r.get("stdout") or "") + (r.get("stderr") or "")).strip()
                tag = "BLOCKED" if r.get("blocked") else f"exit {r.get('exit_code')}"
                lines.append(f"- ran `{a.get('command')}` → {tag}\n  OUTPUT: {out[:900] or '(empty)'}")
        last = self.actions[-1]
        if last.get("kind") == "run" and not (last.get("result") or {}).get("blocked") \
                and (last.get("result") or {}).get("exit_code") == 0:
            if ((last.get("result") or {}).get("stdout") or "").strip():
                lines.append("\nThe last run printed the output above. If it satisfies the "
                             "TASK, reply `DONE: ...`. Otherwise send a corrected FILE + RUN.")
            else:
                lines.append("\nThe last run exited 0 but printed NOTHING. Add a "
                             "`if __name__ == \"__main__\":` block that exercises the code "
                             "and PRINTS results — keep the required functions and paths "
                             "exactly as they are. Then RUN. Do NOT say DONE.")
        elif last.get("kind") in ("read_file", "list_files", "edit_file"):
            lines.append("\nYou inspected/edited files. Next: EDIT or FILE, then RUN (or DONE "
                         "only if a prior green run already satisfied the TASK).")
        else:
            lines.append("\nSend the next EDIT or FILE + RUN (fix the program if the last run "
                         "failed). Do not invent success — use the real OUTPUT above.")
        if self._format_nudge:
            lines.append(self._format_nudge)
        return "\n".join(lines) + ws

    def _auto_run_cmd(self, path: str) -> str:
        """Guess a run command when the model forgot RUN:."""
        p = (path or "main.py").lower()
        if p.endswith(".py"):
            return f"python3 {path}"
        if p.endswith(".js"):
            return f"node {path}"
        if p.endswith(".sh"):
            return f"bash {path}"
        return f"python3 {path}"

    def build_receipt(self, task: str, *, summary: str = "", ran: bool = False,
                      produced_output: bool = False, steps: int = 0,
                      stuck: bool = False, budget_hit: bool = False,
                      error: str = "",
                      syntax: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Auditable trail of the coding loop — the switch reason vs black-box agents."""
        trail: List[Dict[str, Any]] = []
        green_runs = 0
        failed_runs = 0
        verifies = 0
        for a in self.actions:
            kind = a.get("kind")
            if kind == "write_file":
                trail.append({"op": "write", "path": a.get("path"), "bytes": a.get("bytes")})
            elif kind == "edit_file":
                trail.append({"op": "edit", "path": a.get("path"), "ok": a.get("ok"),
                              "note": a.get("note")})
            elif kind == "read_file":
                trail.append({"op": "read", "path": a.get("path"), "bytes": a.get("bytes")})
            elif kind == "list_files":
                trail.append({"op": "list", "n": len(a.get("files") or [])})
            elif kind == "run":
                r = a.get("result") or {}
                ok = r.get("exit_code") == 0 and not r.get("blocked")
                if ok:
                    green_runs += 1
                else:
                    failed_runs += 1
                is_v = bool(a.get("verify")) or "py_compile" in (a.get("command") or "") \
                    or "pytest" in (a.get("command") or "") or "unittest" in (a.get("command") or "")
                if is_v:
                    verifies += 1
                trail.append({
                    "op": "verify" if is_v else "run",
                    "command": (a.get("command") or "")[:160],
                    "exit": r.get("exit_code"),
                    "blocked": bool(r.get("blocked")),
                    "stdout_tail": ((r.get("stdout") or "")[-240:]),
                    "stderr_tail": ((r.get("stderr") or "")[-240:]),
                })
        last_out = _last_stdout(self.actions)
        expected = _expected_outputs(task)
        expected_ok = True
        missing: List[str] = []
        if expected and last_out is not None:
            low = last_out
            for e in expected:
                if e not in low:
                    expected_ok = False
                    missing.append(e)
        core = {
            "kind": "code_agent",
            "task": (task or "")[:400],
            "summary": (summary or "")[:300],
            "ts": int(time.time()),
            "steps": steps,
            "ran": bool(ran),
            "produced_output": bool(produced_output),
            "stuck": bool(stuck),
            "budget_hit": bool(budget_hit),
            "error": (error or "")[:200],
            "files": list(self._files_written),
            "green_runs": green_runs,
            "failed_runs": failed_runs,
            "verifies": verifies,
            "expected": expected,
            "expected_ok": expected_ok,
            "missing_expected": missing,
            "last_stdout_tail": last_out[-300:] if last_out else "",
            "trail": trail[-24:],
            # Part of the hashed core, not bolted on afterwards — the seal has to
            # cover the syntax verdict or it proves nothing about the delivered code.
            "syntax_ok": bool(syntax.get("ok", True)) if syntax else True,
            "syntax_error": (syntax or {}).get("error", "")[:400],
            "syntax_checked": list((syntax or {}).get("checked", [])),
            "ok": bool(ran and produced_output and green_runs > 0 and expected_ok
                       and not stuck and (syntax.get("ok", True) if syntax else True)),
        }
        blob = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        core["receipt_sha"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
        core["verdict"] = (
            "shipped" if core["ok"] else
            ("broken" if not core["syntax_ok"] else
             ("stuck" if stuck else
              ("budget_hit" if budget_hit else
               ("missing_output" if not expected_ok else
                ("ran" if ran else "incomplete")))))
        )
        return core

    def _final_compile_check(self) -> Dict[str, Any]:
        """Does the delivered Python actually parse?

        Runs at the moment of finishing, over the real files on disk. The write-time
        preflight can be left behind: when the step budget runs out mid-repair, the
        loop used to hand back a tree with a SyntaxError in it and still report DONE.
        A receipt that says "shipped" over code that cannot even be imported is the
        one failure this product cannot afford.
        """
        py = [p for p in self._files_written if (p or "").endswith(".py")]
        if not py:
            return {"checked": [], "ok": True, "error": ""}
        try:
            r = self.sb.run("python3 -m py_compile " + " ".join(py),
                            timeout=min(15, max(self.run_timeout, 5)),
                            isolated=self.isolated)
        except Exception as exc:
            return {"checked": py, "ok": True, "error": f"(check skipped: {exc})"[:160]}
        ok = r.get("exit_code") == 0 and not r.get("blocked")
        err = ((r.get("stderr") or "") + (r.get("stdout") or "")).strip()
        return {"checked": py, "ok": bool(ok), "error": "" if ok else err[-400:]}

    def _finish(self, task: str, **kw: Any) -> Iterator[Dict[str, Any]]:
        """Emit code_done + sealed code_receipt (always pair them)."""
        syntax = self._final_compile_check()
        if not syntax["ok"]:
            # Never let a green earlier run launder a broken final tree.
            kw["produced_output"] = False
            kw["summary"] = (
                "INCOMPLETE — the delivered code does not compile: "
                + syntax["error"].splitlines()[-1][:160]
                if syntax["error"] else "INCOMPLETE — the delivered code does not compile"
            )
            yield {"event": "agent_note", "data": {
                "text": "final check: delivered code does NOT compile — reporting it as "
                        "incomplete rather than shipped"}}
        receipt = self.build_receipt(task, syntax=syntax, **kw)
        data = {
            "summary": kw.get("summary", ""),
            "steps": kw.get("steps", 0),
            "ran": kw.get("ran", False),
            "produced_output": kw.get("produced_output", False),
            "stuck": kw.get("stuck", False),
            "budget_hit": kw.get("budget_hit", False),
            "receipt_sha": receipt.get("receipt_sha"),
            "verdict": receipt.get("verdict"),
            "ok": receipt.get("ok"),
            "files": receipt.get("files"),
            "expected_ok": receipt.get("expected_ok"),
        }
        yield {"event": "code_done", "data": data}
        yield {"event": "code_receipt", "data": receipt}

    def run(self, task: str) -> Iterator[Dict[str, Any]]:
        yield {"event": "code_start", "data": {"task": task, "sandbox": self.sb.id}}
        ran_any = False
        produced_output = False
        nudges = 0
        fail_sig = None
        fail_repeats = 0
        parse_fails = 0
        for step in range(self.max_steps):
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"TASK: {task}{self._context(task)}"}]
            yield {"event": "code_thinking", "data": {"step": step, "of": self.max_steps,
                   "ran": ran_any}}
            try:
                raw = self.chat(msgs)
            except Exception as exc:
                yield {"event": "error", "data": {"error": f"model failed: {exc}"[:200]}}
                yield from self._finish(task, summary=f"model failed: {exc}"[:120],
                                        ran=ran_any, produced_output=produced_output,
                                        steps=step, error=str(exc)[:200])
                return
            turn = _parse_turn(raw)
            if turn is None:
                parse_fails += 1
                _tf = _task_target_files(task)
                _pf = _tf[0] if _tf else "main.py"
                self._format_nudge = (
                    "\n\nFORMAT ERROR: Your last reply was not parseable. Reply with ONLY:\n"
                    f"FILE: {_pf}\n```\n# full file contents\n```\n"
                    f"RUN: {self._auto_run_cmd(_pf)}\n"
                    "No prose outside that format."
                )
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "could not parse reply — re-prompting with format fix",
                       "raw": (raw or "")[:300]}}
                if parse_fails >= 3:
                    yield from self._finish(
                        task,
                        summary="Model kept ignoring FILE/RUN format after 3 tries.",
                        budget_hit=True, steps=step, ran=ran_any,
                        produced_output=produced_output)
                    return
                continue
            parse_fails = 0
            self._format_nudge = ""

            # pure DONE → finish (gated on a real, output-producing run)
            pure_done = (
                turn.get("done")
                and not turn.get("file") and not turn.get("run")
                and not turn.get("files") and not turn.get("reads")
                and not turn.get("edits") and not turn.get("list")
            )
            if pure_done:
                if not ran_any and nudges < 2:
                    nudges += 1
                    self._format_nudge = "\n\nYou must FILE + RUN before DONE."
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish without running the code — making it run first"}}
                    continue
                # A path the TASK named is part of the contract, not a suggestion:
                # whoever asked will import exactly that module. Correct code at the
                # wrong path is a total failure, and it used to sail through as DONE.
                missing_files = self._missing_targets(task)
                if missing_files and nudges < 4:
                    nudges += 1
                    want = ", ".join(missing_files)
                    self._format_nudge = (
                        f"\n\nWRONG PATH: the TASK requires {want}, which does not exist "
                        f"in the workspace. Whatever you wrote is at the wrong path, so it "
                        f"cannot be imported. Re-emit the SAME code as `FILE: "
                        f"{missing_files[0]}` (keep the required function and class names "
                        f"exactly as the TASK states), then RUN. Do NOT say DONE yet."
                    )
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": f"required file missing: {want} — redirecting to the "
                                   f"requested path"}}
                    continue
                # Broken code must not be handed back while there is still budget to
                # repair it. The finish-time check keeps the receipt honest; this one
                # actually gets the tree fixed.
                if nudges < 6:
                    syn = self._final_compile_check()
                    if not syn["ok"]:
                        nudges += 1
                        self._format_nudge = (
                            "\n\nTHE DELIVERED CODE DOES NOT COMPILE — you cannot be done.\n"
                            f"{syn['error'][-400:]}\n"
                            "Fix the syntax error with an EDIT block (copy the old text "
                            "verbatim from CURRENT WORKSPACE), then RUN."
                        )
                        yield {"event": "agent_note", "data": {"step": step,
                               "text": "blocked DONE — delivered code does not compile"}}
                        continue
                # A name the TASK said to define is part of the contract too: the caller
                # imports that exact name, so a correct function under a different name
                # is as useless as one at the wrong path.
                missing_syms = self._missing_symbols(task)
                if missing_syms and nudges < 7:
                    nudges += 1
                    names = ", ".join(missing_syms)
                    self._format_nudge = (
                        f"\n\nMISSING REQUIRED NAME: the TASK asks for {names}, which the "
                        f"module does not define. Whatever you named it, rename or add it "
                        f"so `{names}` is importable with the exact signature the TASK "
                        f"states, then RUN. Do NOT say DONE yet."
                    )
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": f"required name missing: {names}"}}
                    continue
                if ran_any and not produced_output and nudges < 3:
                    nudges += 1
                    self._format_nudge = "\n\nLast run printed nothing. Fix the program so it PRINTS."
                    yield {"event": "agent_note", "data": {"step": step,
                           "text": "tried to finish but nothing was printed — making it produce output"}}
                    continue
                # Gate DONE when task named concrete outputs that never appeared.
                expect = _expected_outputs(task)
                last_out = _last_stdout(self.actions)
                missing = [e for e in expect if e not in last_out]
                if missing and nudges < 5:
                    nudges += 1
                    miss = ", ".join(repr(m) for m in missing[:4])
                    self._format_nudge = (
                        f"\n\nOUTPUT MISMATCH. Task expected {miss} in stdout but last green "
                        f"run printed:\n{(last_out or '(empty)')[:400]}\n"
                        "Fix the program so it prints the expected values, then RUN again."
                    )
                    yield {"event": "agent_note", "data": {
                        "text": f"blocked DONE — missing expected output: {miss}"}}
                    continue
                # Multi-file completeness: if written code imports a sibling module
                # that was never created, force the model to write it before DONE.
                if nudges < 6 and self._files_written:
                    contents: Dict[str, str] = {}
                    for p in self._files_written:
                        try:
                            contents[p] = self.sb.read_file(p)
                        except Exception:
                            contents[p] = ""
                    missing_mods = _local_modules_needed(contents)
                    if missing_mods:
                        nudges += 1
                        miss = ", ".join(missing_mods[:6])
                        self._format_nudge = (
                            f"\n\nMISSING MODULES: your code imports {miss} but those files "
                            "were never written. FILE each missing module, then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": f"blocked DONE — missing modules: {miss}"}}
                        continue
                # Gate DONE on test oracle when test files exist (Claude/Codex parity).
                vcmd = _pick_verify_command(self._files_written, task)
                if vcmd and any(_is_test_path(p) for p in self._files_written) and nudges < 4:
                    note = vcmd if len(vcmd) <= 140 else vcmd[:137] + "…"
                    yield {"event": "agent_note", "data": {
                        "text": f"pre-DONE verify: `{note}`"}}
                    yield {"event": "command_started", "data": {"command": vcmd}}
                    vr = self.sb.run(vcmd, timeout=self.run_timeout, isolated=self.isolated)
                    self.actions.append({"kind": "run", "command": vcmd, "result": vr,
                                         "verify": True})
                    yield {"event": "command_finished", "data": {
                        "command": vcmd, "exit_code": vr.get("exit_code"),
                        "stdout": vr.get("stdout", ""), "stderr": vr.get("stderr", ""),
                        "blocked": vr.get("blocked", False), "isolated": True,
                        "verify": True}}
                    if vr.get("exit_code") != 0 or vr.get("blocked"):
                        nudges += 1
                        self._format_nudge = (
                            "\n\nTESTS FAILED before DONE. Fix the failing tests, FILE + RUN again. "
                            "Do not say DONE until tests pass."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "blocked DONE — tests still failing"}}
                        continue
                yield from self._finish(
                    task, summary=turn["done"], steps=step,
                    ran=ran_any, produced_output=produced_output)
                return

            did = False
            written_path = None

            # LIST / READ / EDIT first (inspect before mutate) — Claude/Codex style.
            if turn.get("list"):
                try:
                    files_here = self.sb.list_files()
                except Exception as exc:
                    files_here = []
                    yield {"event": "agent_note", "data": {"text": f"list failed: {exc}"[:160]}}
                self.actions.append({"kind": "list_files", "files": files_here[:80]})
                yield {"event": "agent_note", "data": {
                    "text": "files: " + (", ".join(files_here[:40]) or "(empty)")}}
                did = True

            for path in turn.get("reads") or []:
                try:
                    content = self.sb.read_file(path)
                    self.actions.append({
                        "kind": "read_file", "path": path,
                        "bytes": len(content or ""), "content": content or "",
                    })
                    yield {"event": "agent_note", "data": {
                        "text": f"read {path} ({len(content or '')} bytes)",
                        "path": path, "preview": (content or "")[:400]}}
                    did = True
                except Exception as exc:
                    self.actions.append({
                        "kind": "read_file", "path": path, "bytes": 0,
                        "content": f"(read failed: {exc})",
                    })
                    yield {"event": "agent_note", "data": {"text": f"read {path} failed: {exc}"[:160]}}
                    did = True

            for path, old, new in turn.get("edits") or []:
                try:
                    cur = self.sb.read_file(path)
                except Exception as exc:
                    self.actions.append({"kind": "edit_file", "path": path, "ok": False,
                                         "note": f"read failed: {exc}"})
                    yield {"event": "agent_note", "data": {
                        "text": f"edit {path} failed — cannot read: {exc}"[:160]}}
                    did = True
                    continue
                if old not in cur:
                    # Nothing changed. Steer at the workspace block instead of leaving a
                    # content-free "not found" — that was a dead end whose only escape
                    # was a blind full rewrite.
                    self.actions.append({
                        "kind": "edit_file", "path": path, "ok": False,
                        "note": "old text did NOT match byte-for-byte, so NOTHING changed. "
                                "Do not guess it again — copy the old text verbatim out of "
                                f"the CURRENT WORKSPACE block for {path} (watch indentation), "
                                "or send a full FILE rewrite."})
                    yield {"event": "agent_note", "data": {
                        "text": f"edit {path} — old text not found; showing exact file content"}}
                    did = True
                    continue
                if cur.count(old) > 1:
                    self.actions.append({
                        "kind": "edit_file", "path": path, "ok": False,
                        "note": f"old text matches {cur.count(old)} places — nothing changed. "
                                "Extend it with surrounding lines from CURRENT WORKSPACE "
                                "until it is unique."})
                    yield {"event": "agent_note", "data": {
                        "text": f"edit {path} — old text matches {cur.count(old)} times; make it unique"}}
                    did = True
                    continue
                updated = cur.replace(old, new, 1)
                try:
                    fc = self.sb.write_file(path, updated, reason="edit")
                    self.actions.append({"kind": "edit_file", "path": path, "ok": True,
                                         "note": f"{len(old)}→{len(new)} chars"})
                    if path not in self._files_written:
                        self._files_written.append(path)
                    written_path = path
                    yield {"event": "file_changed", "data": {"path": path,
                           "diff": (fc.get("diff") or "")[:_DIFF_CAP], "bytes": len(updated),
                           "edit": True}}
                    did = True
                    if (path or "").endswith(".py"):
                        # mark for preflight after edits (shared with write path)
                        turn.setdefault("_py_touch", []).append(path)
                except Exception as exc:
                    self.actions.append({"kind": "edit_file", "path": path, "ok": False,
                                         "note": str(exc)[:120]})
                    yield {"event": "agent_note", "data": {"text": f"edit write failed: {exc}"[:160]}}
                    did = True

            file_list = turn.get("files") or (
                [turn["file"]] if turn.get("file") and turn["file"][1] is not None else []
            )
            syntax_blocked = False
            for path, content in file_list:
                if content is None:
                    continue
                written_path = path
                try:
                    fc = self.sb.write_file(path, content, reason="")
                    self.actions.append({"kind": "write_file", "path": path, "bytes": len(content)})
                    if path not in self._files_written:
                        self._files_written.append(path)
                    yield {"event": "file_changed", "data": {"path": path,
                           "diff": (fc.get("diff") or "")[:_DIFF_CAP], "bytes": len(content)}}
                    did = True
                    # Pre-flight syntax gate: catch SyntaxError before a full RUN
                    # burns a step (speed + reliability vs Claude/Codex).
                    if (path or "").endswith(".py"):
                        vcmd = f"python3 -m py_compile {path}"
                        yield {"event": "command_started", "data": {"command": vcmd, "verify": True}}
                        vr = self.sb.run(vcmd, timeout=min(10, self.run_timeout),
                                         isolated=self.isolated)
                        self.actions.append({"kind": "run", "command": vcmd,
                                             "result": vr, "verify": True})
                        yield {"event": "command_finished", "data": {
                            "command": vcmd, "exit_code": vr.get("exit_code"),
                            "stdout": vr.get("stdout", ""), "stderr": vr.get("stderr", ""),
                            "blocked": vr.get("blocked", False), "isolated": True,
                            "verify": True}}
                        if vr.get("exit_code") != 0 or vr.get("blocked"):
                            syntax_blocked = True
                            err = ((vr.get("stderr") or "") + (vr.get("stdout") or "")).strip()
                            self._format_nudge = (
                                f"\n\nSYNTAX ERROR in `{path}` (py_compile failed).\n"
                                f"{err[:500]}\nFix it with an EDIT block (copy the old text "
                                f"verbatim from CURRENT WORKSPACE); use a full FILE rewrite "
                                f"only if the file needs restructuring. Then RUN."
                            )
                            yield {"event": "agent_note", "data": {
                                "text": f"py_compile failed for {path} — fix before RUN"}}
                except Exception as exc:
                    yield {"event": "agent_note", "data": {"text": f"write failed: {exc}"[:160]}}
            # py_compile any edit-touched files not already covered by write preflight
            for path in turn.get("_py_touch") or []:
                if any(p == path for p, _ in (file_list or [])):
                    continue
                vcmd = f"python3 -m py_compile {path}"
                yield {"event": "command_started", "data": {"command": vcmd, "verify": True}}
                vr = self.sb.run(vcmd, timeout=min(10, self.run_timeout), isolated=self.isolated)
                self.actions.append({"kind": "run", "command": vcmd, "result": vr, "verify": True})
                yield {"event": "command_finished", "data": {
                    "command": vcmd, "exit_code": vr.get("exit_code"),
                    "stdout": vr.get("stdout", ""), "stderr": vr.get("stderr", ""),
                    "blocked": vr.get("blocked", False), "isolated": True, "verify": True}}
                if vr.get("exit_code") != 0 or vr.get("blocked"):
                    syntax_blocked = True
                    err = ((vr.get("stderr") or "") + (vr.get("stdout") or "")).strip()
                    self._format_nudge = (
                        f"\n\nSYNTAX ERROR in `{path}` after EDIT (py_compile failed).\n"
                        f"{err[:500]}\nFix again before RUN."
                    )
                    yield {"event": "agent_note", "data": {
                        "text": f"py_compile failed for edited {path}"}}
            # If model wrote/edited a file but forgot RUN, auto-run once
            # (unless syntax preflight failed — don't waste a run on broken code).
            cmd = turn.get("run")
            if syntax_blocked:
                cmd = None
            if not cmd and written_path and did and (file_list or turn.get("edits")) and not syntax_blocked:
                cmd = self._auto_run_cmd(written_path)
                yield {"event": "agent_note", "data": {
                    "text": f"no RUN line — auto-running `{cmd}`"}}
            if cmd:
                yield {"event": "command_started", "data": {"command": cmd}}
                r = self.sb.run(cmd, timeout=self.run_timeout, isolated=self.isolated)
                # Auto-retry python → python3 when the jail only has python3
                # (common Claude Code / Codex host difference that burns a step).
                err_probe = ((r.get("stderr") or "") + "\n" + (r.get("stdout") or "")).strip()
                if (r.get("exit_code") != 0 or r.get("blocked")) and re.match(
                    r"^\s*python(\s|$)", cmd or ""
                ) and re.search(
                    r"python: (?:not found|command not found)|No such file or directory: ['\"]?python['\"]?",
                    err_probe, re.I,
                ):
                    alt = re.sub(r"^\s*python\b", "python3", cmd, count=1)
                    yield {"event": "agent_note", "data": {
                        "text": f"python missing — retrying as `{alt}`"}}
                    yield {"event": "command_started", "data": {"command": alt}}
                    r = self.sb.run(alt, timeout=self.run_timeout, isolated=self.isolated)
                    cmd = alt
                ran_any = True
                ok = r.get("exit_code") == 0 and not r.get("blocked")
                if ok and (r.get("stdout") or "").strip():
                    produced_output = True
                elif ok and _is_test_command(cmd) and (r.get("stderr") or "").strip():
                    # A green unittest/pytest run reports "Ran N tests / OK" on STDERR
                    # with STDOUT empty. Without this, a genuinely passing suite reads as
                    # "printed nothing": DONE stays blocked, the verify oracle (gated on
                    # produced_output) never fires, and the receipt marks a correct run
                    # incomplete. Scoped to test runners so the anti-vacuous-success
                    # guard still holds for ordinary programs.
                    produced_output = True
                self.actions.append({"kind": "run", "command": cmd, "result": r})
                yield {"event": "command_finished", "data": {
                    "command": cmd, "exit_code": r.get("exit_code"),
                    "stdout": r.get("stdout", ""), "stderr": r.get("stderr", ""),
                    "blocked": r.get("blocked", False), "isolated": r.get("isolated", True)}}
                did = True
                # Flail guard: if the same failure repeats, stop and report honestly
                # instead of burning every step on identical errors.
                if not ok:
                    err_full = ((r.get("stderr") or "") + "\n" + (r.get("stdout") or "")).strip()
                    err = err_full.splitlines()
                    sig = (err[-1][:90] if err else "fail")
                    # Auto-coach: ModuleNotFoundError → write the missing sibling file
                    # (Claude/Codex users expect the agent to notice import gaps).
                    m_miss = re.search(
                        r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]",
                        err_full,
                    ) or re.search(
                        r"ImportError:\s*cannot import name ['\"]([^'\"]+)['\"]",
                        err_full,
                    )
                    third_party_miss = False
                    if m_miss:
                        mod = m_miss.group(1).split(".")[0]
                        # Third-party / non-stdlib: do NOT invent FILE: requests.py —
                        # rewrite with stdlib (sandbox has no pip/network).
                        if mod and mod.lower() in _TEST_FRAMEWORK_MODS:
                            # Must be tested BEFORE the third-party branch: that one
                            # coaches "rewrite with stdlib only", which a model reads as
                            # permission to DELETE the test file it was asked for. Keep
                            # the tests, change only their dialect.
                            third_party_miss = True
                            self._format_nudge = (
                                f"\n\n`{mod}` is not installed in the jail. KEEP the test "
                                "file — convert it to stdlib unittest: subclass "
                                "unittest.TestCase and use self.assertEqual / "
                                "self.assertRaises instead of bare asserts, and drop the "
                                f"`import {mod}` line. That shape also runs under pytest. "
                                "Do NOT delete or weaken any test. Then RUN again."
                            )
                            yield {"event": "agent_note", "data": {
                                "text": f"no {mod} in the jail — converting tests to unittest"}}
                        elif mod and (mod in _THIRD_PARTY_MODS or mod.lower() in _THIRD_PARTY_MODS):
                            third_party_miss = True
                            self._format_nudge = (
                                f"\n\nTHIRD-PARTY IMPORT BLOCKED: `{mod}` is not available "
                                "(no pip/network in the jail). Rewrite using Python stdlib only "
                                "(urllib, json, http.server, csv, re, pathlib, …). "
                                "Remove the import, then RUN again. Do not claim DONE yet."
                            )
                            yield {"event": "agent_note", "data": {
                                "text": f"no pip — rewrite without `{mod}` (stdlib only)"}}
                        elif mod and mod.isidentifier() and f"{mod}.py" not in self._files_written:
                            self._format_nudge = (
                                f"\n\nIMPORT ERROR: missing module `{mod}`. "
                                f"Write FILE: {mod}.py with the needed code, update imports if "
                                "required, then RUN again. Do not claim DONE yet."
                            )
                            yield {"event": "agent_note", "data": {
                                "text": f"import failed — need FILE: {mod}.py"}}
                    # SyntaxError / IndentationError / NameError → surgical fix coach
                    m_syn = re.search(
                        r'File "([^"]+)", line (\d+)[^\n]*\n(?:[^\n]*\n){0,2}\s*(SyntaxError|IndentationError):\s*(.+)',
                        err_full,
                    )
                    m_name = re.search(
                        r"NameError:\s*name ['\"]([^'\"]+)['\"] is not defined",
                        err_full,
                    )
                    if m_syn and not m_miss:
                        fpath, line_no, etype, emsg = m_syn.group(1), m_syn.group(2), m_syn.group(3), m_syn.group(4).strip()
                        base = fpath.rsplit("/", 1)[-1]
                        self._format_nudge = (
                            f"\n\n{etype} in `{base}` line {line_no}: {emsg[:160]}\n"
                            f"Use EDIT: {base} (or rewrite FILE: {base}) to fix ONLY that issue, "
                            "then RUN again. Do not start over unless necessary."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": f"{etype} line {line_no} in {base} — surgical fix"}}
                    elif m_name and not m_miss:
                        missing_name = m_name.group(1)
                        self._format_nudge = (
                            f"\n\nNameError: `{missing_name}` is not defined. "
                            "Define it (or fix the typo) in the relevant FILE, then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": f"NameError — `{missing_name}` not defined"}}
                    m_assert = re.search(r"AssertionError(?::\s*(.+))?", err_full)
                    if m_assert and not m_miss and not m_syn and not m_name:
                        detail = (m_assert.group(1) or "").strip()[:160]
                        self._format_nudge = (
                            "\n\nASSERT FAILED"
                            + (f": {detail}" if detail else ".")
                            + " Fix the logic (or the assert) so the check passes, then RUN again. "
                            "Do not say DONE until asserts are green."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "AssertionError — fix logic/tests before DONE"}}
                    # Timeouts / kills → force finite, non-interactive rewrite
                    if re.search(r"timeout|timed out|killed|time.?limit", err_full, re.I):
                        self._format_nudge = (
                            "\n\nTIMEOUT: the program did not exit in time. Remove infinite loops, "
                            "servers, and input(). Use fixed sample data and print results, then RUN."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "timeout/kill — rewrite to exit quickly"}}
                    m_fnf = re.search(
                        r"FileNotFoundError:.*No such file or directory: ['\"]([^'\"]+)['\"]",
                        err_full,
                    ) or re.search(
                        r"can't open file ['\"]([^'\"]+)['\"]",
                        err_full,
                    )
                    if m_fnf and not m_miss:
                        missing = m_fnf.group(1).rsplit("/", 1)[-1]
                        self._format_nudge = (
                            f"\n\nFILE NOT FOUND: `{missing}`. Write FILE: {missing} "
                            "(or fix the RUN path), then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": f"missing file `{missing}` — write it before RUN"}}
                    if re.search(r"ZeroDivisionError", err_full) and not m_miss:
                        self._format_nudge = (
                            "\n\nZeroDivisionError: guard the divisor (or fix the math), "
                            "then RUN again. Do not claim DONE."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "ZeroDivisionError — guard divisors"}}
                    # AttributeError / UnboundLocalError — common model flail modes
                    m_attr = re.search(
                        r"AttributeError:\s*'([^']+)' object has no attribute '([^']+)'",
                        err_full,
                    ) or re.search(
                        r"AttributeError:\s*module '([^']+)' has no attribute '([^']+)'",
                        err_full,
                    ) or re.search(r"AttributeError:\s*(.+)", err_full)
                    if m_attr and not m_miss and not m_syn and not third_party_miss:
                        detail = (m_attr.group(0) if m_attr.lastindex is None
                                  else m_attr.group(0))[:140]
                        self._format_nudge = (
                            f"\n\nAttributeError: {detail}\n"
                            "Fix the object/API (typo, wrong type, missing method), "
                            "then RUN again. Prefer EDIT over full rewrite."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": f"AttributeError — {detail[:80]}"}}
                    if re.search(r"UnboundLocalError", err_full) and not m_miss:
                        self._format_nudge = (
                            "\n\nUnboundLocalError: a name is assigned later in the function "
                            "but read earlier. Initialize it before use (or use a different name), "
                            "then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "UnboundLocalError — init before use"}}
                    if re.search(r"RecursionError", err_full) and not m_miss:
                        self._format_nudge = (
                            "\n\nRecursionError: infinite or too-deep recursion. Add a base case "
                            "(or rewrite iteratively), then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "RecursionError — add base case / iterate"}}
                    if re.search(r"JSONDecodeError|json\.decoder", err_full) and not m_miss:
                        self._format_nudge = (
                            "\n\nJSONDecodeError: invalid JSON input. Validate/fix the string "
                            "(or use a fixed sample), catch errors, then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "JSONDecodeError — fix JSON input"}}
                    if re.search(r"Unicode(Encode|Decode)Error", err_full) and not m_miss:
                        self._format_nudge = (
                            "\n\nUnicode error: open files with encoding='utf-8' (and errors= "
                            "'replace' if needed), or encode/decode explicitly. Then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "Unicode error — use utf-8 encoding"}}
                    if re.search(r"EOFError", err_full) and not m_miss:
                        self._format_nudge = (
                            "\n\nEOFError: input() is not available in the jail. Use fixed sample "
                            "values (no interactive input), then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": "EOFError — remove input(); use fixed samples"}}
                    if re.search(r"PermissionError|IsADirectoryError|NotADirectoryError", err_full) and not m_miss:
                        et = re.search(
                            r"(PermissionError|IsADirectoryError|NotADirectoryError)(:\s*[^\n]+)?",
                            err_full,
                        )
                        label = et.group(0)[:120] if et else "path error"
                        self._format_nudge = (
                            f"\n\nPATH ERROR: {label}\n"
                            "Use a file path (not a directory), write the file first, and stay "
                            "inside the sandbox cwd. Then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": f"path error — {label[:80]}"}}
                    if re.search(r"IndexError|KeyError|TypeError|ValueError", err_full) and not m_miss and not m_syn and not m_attr:
                        et = re.search(r"(IndexError|KeyError|TypeError|ValueError)(:\s*[^\n]+)?", err_full)
                        label = et.group(0)[:120] if et else "runtime error"
                        self._format_nudge = (
                            f"\n\nRUNTIME ERROR: {label}\n"
                            "Fix the root cause in the FILE (bounds, keys, types), then RUN again."
                        )
                        yield {"event": "agent_note", "data": {
                            "text": f"runtime error — {label[:80]}"}}
                    fail_repeats = fail_repeats + 1 if sig == fail_sig else 0
                    fail_sig = sig
                    if fail_repeats >= 2:
                        yield from self._finish(
                            task,
                            summary=("Couldn't get a clean run in the sandbox — the same error "
                                     "kept recurring. This task likely needs the network, a GUI, "
                                     "a server, or live input, which the isolated sandbox doesn't "
                                     "have. The code is written above."),
                            ran=ran_any, produced_output=produced_output, stuck=True,
                            steps=step)
                        return
                else:
                    fail_repeats = 0
                    fail_sig = None
                    # Exit 0 but empty stdout when the task wants printed results
                    if ok and not (r.get("stdout") or "").strip():
                        expect = _expected_outputs(task)
                        if expect or re.search(r"\bprint\b", task or "", re.I):
                            self._format_nudge = (
                                "\n\nEXIT 0 BUT EMPTY STDOUT. The program must PRINT results "
                                "(use print(...)). Rewrite so it prints, then RUN again."
                            )
                            yield {"event": "agent_note", "data": {
                                "text": "empty stdout — add print() before DONE"}}
                            ok = False  # keep looping; do not auto-DONE
                    # Competitive bar: after a green run, prefer a real test oracle
                    # (pytest/unittest) when test files exist; else py_compile on
                    # multi-file / test-oriented tasks so we never DONE on garbage.
                    if ok and produced_output:
                        vcmd = _pick_verify_command(self._files_written, task)
                        if vcmd:
                            # Avoid re-running the exact same verify after every green
                            # run in a flail loop — only once per unique command set.
                            last_v = next(
                                (a for a in reversed(self.actions)
                                 if a.get("kind") == "run" and a.get("command") == vcmd),
                                None,
                            )
                            if last_v and last_v.get("result", {}).get("exit_code") == 0:
                                pass  # already verified cleanly
                            else:
                                note = vcmd if len(vcmd) < 140 else vcmd[:137] + "…"
                                yield {"event": "agent_note", "data": {
                                    "text": f"verify: `{note}`"}}
                                yield {"event": "command_started", "data": {"command": vcmd}}
                                vr = self.sb.run(vcmd, timeout=self.run_timeout,
                                                 isolated=self.isolated)
                                self.actions.append({"kind": "run", "command": vcmd,
                                                     "result": vr, "verify": True})
                                yield {"event": "command_finished", "data": {
                                    "command": vcmd, "exit_code": vr.get("exit_code"),
                                    "stdout": vr.get("stdout", ""), "stderr": vr.get("stderr", ""),
                                    "blocked": vr.get("blocked", False), "isolated": True,
                                    "verify": True}}
                                if vr.get("exit_code") != 0 or vr.get("blocked"):
                                    ok = False
                                    produced_output = True  # keep working
                                    self._format_nudge = (
                                        "\n\nVERIFY FAILED. Fix syntax/tests, then RUN again. "
                                        "Do not say DONE."
                                    )
                        # Auto-DONE when oracles are green — speed-to-value without
                        # burning another model turn waiting for "DONE:".
                        # A green oracle on the wrong filename is still a failure, so the
                        # required-path check gates the auto-finish too — otherwise this
                        # path just routes around it.
                        if (ok and not self._missing_targets(task)
                                and not self._missing_symbols(task)):
                            auto = _task_oracle_satisfied(
                                task, self.actions, self._files_written)
                            if auto:
                                yield {"event": "agent_note", "data": {
                                    "text": f"oracle green — finishing ({auto})"}}
                                yield from self._finish(
                                    task, summary=auto, steps=step,
                                    ran=ran_any, produced_output=produced_output)
                                return
            if not did:
                yield {"event": "agent_note", "data": {"step": step,
                       "text": "no FILE or RUN in the reply", "raw": (raw or "")[:200]}}
                self._format_nudge = (
                    "\n\nYou must include FILE: + fenced code + RUN: on every turn until DONE."
                )
        yield from self._finish(
            task, summary="reached the step budget", budget_hit=True,
            steps=self.max_steps, ran=ran_any, produced_output=produced_output)
